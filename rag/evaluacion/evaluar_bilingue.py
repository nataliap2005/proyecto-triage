"""Compara la recuperación densa solo en español con la búsqueda bilingüe (español + inglés).

Ejecutar desde la raíz del proyecto:
    python -m rag.evaluacion.evaluar_bilingue

Usa las mismas 20 preguntas anotadas y las mismas métricas que evaluar_recuperacion.py.
La traducción al inglés se pide a Groq una sola vez por pregunta y se guarda en
resultados/traducciones_consultas.json (si ya existe, se reutiliza: no vuelve a llamar a Groq).
No modifica Neon y solo consulta guías publicadas.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from rag import recuperar
from rag.cliente_llm import traducir_consulta
from rag.evaluacion.evaluar_recuperacion import metricas, validar_preguntas, validar_referencias
from rag.motor import combinar

BASE = Path(__file__).resolve().parent
RESULTADOS = BASE / 'resultados'


def promedio(filas, clave):
    return sum(f[clave] for f in filas) / len(filas)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preguntas', type=Path, default=BASE / 'preguntas_prueba.json')
    parser.add_argument('--pausa', type=float, default=3.0, help='segundos entre traducciones (límite de Groq)')
    args = parser.parse_args()

    preguntas = json.loads(args.preguntas.read_text(encoding='utf-8-sig'))
    validar_preguntas(preguntas)
    RESULTADOS.mkdir(exist_ok=True)
    ruta_trad = RESULTADOS / 'traducciones_consultas.json'
    traducciones = json.loads(ruta_trad.read_text(encoding='utf-8')) if ruta_trad.exists() else {}

    for p in preguntas:
        if p['id'] not in traducciones:
            traducciones[p['id']] = traducir_consulta(p['pregunta'])
            ruta_trad.write_text(json.dumps(traducciones, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"{p['id']}: {traducciones[p['id']]}")
            time.sleep(args.pausa)

    from sentence_transformers import SentenceTransformer
    print('Cargando modelo de embeddings una sola vez...')
    modelo = SentenceTransformer(recuperar.MODELO)
    condicion, params = recuperar._filtro(None)

    filas = []
    with recuperar._conectar() as db:
        db.set_session(readonly=True)
        with db.cursor() as cur:
            validar_referencias(cur, preguntas)
            for p in preguntas:
                es = recuperar._dense(cur, p['pregunta'], condicion, params, 20, modelo)
                en_texto = traducciones.get(p['id'])
                bi = es
                if en_texto:
                    en = recuperar._dense(cur, en_texto, condicion, params, 20, modelo)
                    bi = combinar([es, en], 20)
                m_es = metricas([d['id_fragmento'] for d in es], p['fragmentos_relevantes'])
                m_bi = metricas([d['id_fragmento'] for d in bi], p['fragmentos_relevantes'])
                filas.append({'id': p['id'], 'fuente_esperada': p.get('fuente_esperada'),
                              'consulta_en': en_texto,
                              **{f'es_{k}': v for k, v in m_es.items()},
                              **{f'bi_{k}': v for k, v in m_bi.items()}})

    claves = ('recall_at_1', 'recall_at_3', 'hit_at_1', 'hit_at_3', 'rr_at_20')
    resumen = {modo: {k: round(promedio(filas, f'{pref}_{k}'), 3) for k in claves}
               for modo, pref in (('dense_espanol', 'es'), ('dense_bilingue', 'bi'))}
    salida = {'fecha': datetime.now(timezone.utc).isoformat(), 'preguntas': len(filas),
              'modelo_embedding': recuperar.MODELO, 'resumen': resumen, 'detalle': filas}
    (RESULTADOS / 'evaluacion_bilingue.json').write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\nMétrica        Solo español   Bilingüe')
    for k in claves:
        print(f"{k:<14} {resumen['dense_espanol'][k]:>12.3f} {resumen['dense_bilingue'][k]:>10.3f}")
    mejor = sum(f['bi_rr_at_20'] > f['es_rr_at_20'] for f in filas)
    peor = sum(f['bi_rr_at_20'] < f['es_rr_at_20'] for f in filas)
    print(f'\nPreguntas que mejoran: {mejor} · empeoran: {peor} · iguales: {len(filas) - mejor - peor}')
    print(f"Detalle guardado en {RESULTADOS / 'evaluacion_bilingue.json'}")


if __name__ == '__main__':
    main()
