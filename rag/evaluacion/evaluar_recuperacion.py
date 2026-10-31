"""Evalúa Recall@1, Recall@3 y MRR@20 de BM25, Dense e híbrido.

Ejecutar desde la raíz del proyecto:
    python -m rag.evaluacion.evaluar_recuperacion

No modifica Neon, no utiliza Groq y solo consulta guías publicadas.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from rag import recuperar

BASE = Path(__file__).resolve().parent
METODOS = ('bm25', 'dense', 'hibrido')


def metricas(ids, relevantes):
    """Recall@k sobre IDs relevantes anotados; MRR@20 sobre el primer acierto."""
    ids = list(ids)
    relevantes = set(relevantes)
    if not relevantes:
        raise ValueError('No se puede evaluar una pregunta sin fragmentos relevantes')
    salida = {}
    for k in (1, 3):
        salida[f'recall_at_{k}'] = len(relevantes.intersection(ids[:k])) / len(relevantes)
        salida[f'hit_at_{k}'] = int(bool(relevantes.intersection(ids[:k])))
    primer_rango = next((i for i, frag in enumerate(ids[:20], 1) if frag in relevantes), None)
    salida['primer_rango_relevante'] = primer_rango
    salida['rr_at_20'] = 1.0 / primer_rango if primer_rango else 0.0
    return salida


def validar_preguntas(preguntas):
    if not isinstance(preguntas, list) or len(preguntas) < 20:
        raise ValueError('El JSON debe contener al menos 20 preguntas')
    vistos = set()
    for p in preguntas:
        if not isinstance(p, dict) or not all(k in p for k in ('id', 'pregunta', 'fragmentos_relevantes')):
            raise ValueError('Cada pregunta debe incluir id, pregunta y fragmentos_relevantes')
        if p['id'] in vistos:
            raise ValueError(f"ID de pregunta duplicado: {p['id']}")
        vistos.add(p['id'])
        if not isinstance(p['pregunta'], str) or not p['pregunta'].strip():
            raise ValueError(f"Pregunta vacía: {p['id']}")
        relevantes = p['fragmentos_relevantes']
        if not isinstance(relevantes, list) or not relevantes or not all(isinstance(x, str) and x for x in relevantes):
            raise ValueError(f"Sin referencias válidas: {p['id']}")
        if len(set(relevantes)) != len(relevantes):
            raise ValueError(f"Referencias duplicadas: {p['id']}")


def validar_referencias(cur, preguntas):
    ids = sorted({frag for p in preguntas for frag in p['fragmentos_relevantes']})
    cur.execute('''SELECT id_fragmento, fuente FROM rag_fragmentos
                   WHERE tipo='guia' AND estado='publicada' AND id_fragmento = ANY(%s)''', (ids,))
    encontrados = dict(cur.fetchall())
    faltantes = set(ids) - set(encontrados)
    if faltantes:
        raise ValueError('Referencias no encontradas como guías publicadas: ' + ', '.join(sorted(faltantes)))
    for p in preguntas:
        esperado = p.get('fuente_esperada')
        for frag in p['fragmentos_relevantes']:
            if esperado and encontrados[frag] != esperado:
                raise ValueError(f"{p['id']}: {frag} corresponde a {encontrados[frag]}, no a {esperado}")


def recuperar_tres(cur, pregunta, modelo, k=20):
    """Mismo algoritmo que rag.recuperar.buscar; reutiliza conexión y modelo."""
    condicion, params = recuperar._filtro(None)
    # En híbrido se toman 80 candidatos por rama: max(30, top_k*4).
    n = max(30, k * 4)
    lexical = recuperar._bm25(cur, pregunta, condicion, params, n)
    semantica = recuperar._dense(cur, pregunta, condicion, params, n, modelo)
    fusion = {}
    for lista in (lexical, semantica):
        for posicion, doc in enumerate(lista, 1):
            clave = doc['id_fragmento']
            if clave not in fusion:
                fusion[clave] = {**doc, 'puntaje': 0.0}
            fusion[clave]['puntaje'] += 1.0 / (60 + posicion)
    hibrido = sorted(fusion.values(), key=lambda d: d['puntaje'], reverse=True)[:k]
    return {'bm25': lexical[:k], 'dense': semantica[:k], 'hibrido': hibrido}


def guardar_csv(ruta, filas, campos):
    with ruta.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(filas)


def graficar(resumen, salida):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print('Matplotlib no instalado; se omite el gráfico.')
        return
    etiquetas = ['Recall@1', 'Recall@3', 'MRR@20']
    claves = ['recall_at_1', 'recall_at_3', 'mrr_at_20']
    xs = list(range(len(etiquetas)))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ancho = 0.24
    for i, metodo in enumerate(METODOS):
        valores = [resumen[metodo][clave] for clave in claves]
        barras = ax.bar([x + (i - 1) * ancho for x in xs], valores, width=ancho, label=metodo.upper())
        ax.bar_label(barras, fmt='%.2f', padding=2, fontsize=8)
    ax.set_xticks(xs, etiquetas)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel('Promedio de las preguntas')
    ax.set_title('Evaluación de recuperación RAG clínico')
    ax.legend()
    fig.tight_layout()
    fig.savefig(salida / 'comparacion_metodos.png', dpi=170)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preguntas', type=Path, default=BASE / 'preguntas_prueba.json')
    parser.add_argument('--salida', type=Path, default=BASE / 'resultados')
    args = parser.parse_args()
    preguntas = json.loads(args.preguntas.read_text(encoding='utf-8-sig'))
    validar_preguntas(preguntas)
    args.salida.mkdir(parents=True, exist_ok=True)

    from sentence_transformers import SentenceTransformer
    print('Cargando modelo de embeddings una sola vez...')
    modelo = SentenceTransformer(recuperar.MODELO)
    detalle = []
    rankings = []
    with recuperar._conectar() as db:
        db.set_session(readonly=True)
        with db.cursor() as cur:
            validar_referencias(cur, preguntas)
            print(f'Referencias verificadas. Evaluando {len(preguntas)} preguntas × 3 métodos...')
            for i, p in enumerate(preguntas, 1):
                resultados = recuperar_tres(cur, p['pregunta'], modelo, k=20)
                for metodo in METODOS:
                    documentos = resultados[metodo]
                    ids = [d['id_fragmento'] for d in documentos]
                    m = metricas(ids, p['fragmentos_relevantes'])
                    detalle.append({'id_pregunta': p['id'], 'pregunta': p['pregunta'],
                                    'metodo': metodo, 'n_relevantes': len(p['fragmentos_relevantes']),
                                    'n_recuperados': len(ids), **m})
                    for rango, doc in enumerate(documentos, 1):
                        rankings.append({'id_pregunta': p['id'], 'metodo': metodo, 'rango': rango,
                                         'id_fragmento': doc['id_fragmento'],
                                         'relevante': int(doc['id_fragmento'] in p['fragmentos_relevantes']),
                                         'fuente': doc['fuente'], 'puntaje': float(doc['puntaje'])})
                print(f'[{i:02d}/{len(preguntas)}] {p["id"]} completada')

    resumen = {}
    for metodo in METODOS:
        filas = [r for r in detalle if r['metodo'] == metodo]
        resumen[metodo] = {
            'n_preguntas': len(filas),
            'recall_at_1': sum(r['recall_at_1'] for r in filas) / len(filas),
            'recall_at_3': sum(r['recall_at_3'] for r in filas) / len(filas),
            'mrr_at_20': sum(r['rr_at_20'] for r in filas) / len(filas),
            'hit_at_1': sum(r['hit_at_1'] for r in filas) / len(filas),
            'hit_at_3': sum(r['hit_at_3'] for r in filas) / len(filas),
        }
    campos_detalle = ['id_pregunta','pregunta','metodo','n_relevantes','n_recuperados',
                      'recall_at_1','hit_at_1','recall_at_3','hit_at_3','primer_rango_relevante','rr_at_20']
    guardar_csv(args.salida / 'metricas_por_pregunta.csv', detalle, campos_detalle)
    guardar_csv(args.salida / 'rankings_recuperacion.csv', rankings,
                ['id_pregunta','metodo','rango','id_fragmento','relevante','fuente','puntaje'])
    guardar_csv(args.salida / 'resumen_metricas.csv',
                [{'metodo': m, **resumen[m]} for m in METODOS],
                ['metodo','n_preguntas','recall_at_1','recall_at_3','mrr_at_20','hit_at_1','hit_at_3'])
    (args.salida / 'evaluacion_recuperacion.json').write_text(
        json.dumps({'fecha_utc': datetime.now(timezone.utc).isoformat(),
                    'modelo_embedding': recuperar.MODELO, 'k_max': 20,
                    'nota': 'Recall y MRR sobre relevancia anotada, no exhaustiva; rankings sin expansion de contexto.',
                    'resumen': resumen, 'detalle': detalle}, ensure_ascii=False, indent=2), encoding='utf-8')
    graficar(resumen, args.salida)
    print('\nRESULTADOS (promedios):')
    for metodo in METODOS:
        r = resumen[metodo]
        print(f'{metodo:8s} Recall@1={r["recall_at_1"]:.4f}  Recall@3={r["recall_at_3"]:.4f}  MRR@20={r["mrr_at_20"]:.4f}')
    print(f'\nArchivos guardados en: {args.salida.resolve()}')
    print('Nota: la anotación de fragmentos relevantes no es exhaustiva.')


if __name__ == '__main__':
    main()
