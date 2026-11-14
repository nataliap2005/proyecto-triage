"""Búsqueda complementaria de referencias para P04, P05, P10, P12, P14 y P17.
Ejecutar desde raíz: python rag/evaluacion/buscar_fragmentos_faltantes.py
Solo lectura de guías publicadas en Neon. Sin Groq ni embeddings nuevos.
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
from collections import defaultdict

from dotenv import load_dotenv
import psycopg2

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
load_dotenv(ROOT / 'back' / 'pass.env', override=False)

# Términos de búsqueda en español e inglés, ajustados a cada fuente.
CONFIG = {
 'P04': {'terminos': ['información', 'paciente', 'acompañantes', 'tiempos', 'clasificación', 'ansiedad'], 'paginas': [1,2,3,4]},
 'P05': {'terminos': ['heart rate', 'respiratory rate', 'systolic', 'consciousness', 'oxygen saturation', 'temperature', 'physiological observations'], 'paginas': [7,11,12]},
 'P10': {'terminos': ['pneumothorax', 'tension', 'chest trauma', 'eFAST', 'decompression', 'imaging'], 'paginas': [6,7,8]},
 'P12': {'terminos': ['1.8.1', '1.8.7', 'primary survey', 'record', 'documentation', 'handover'], 'paginas': [14,15,16]},
 'P14': {'terminos': ['troponin', '99th percentile', 'sexes', 'time since', 'chronically elevated', 'renal'], 'paginas': [13,14,15]},
 'P17': {'terminos': ['ABCDE', 'vía aérea', 'respiración', 'circulación', 'disfunción neurológica', 'exposición'], 'paginas': [18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40]},
}


def normalizar(s):
    return re.sub(r'\s+', ' ', s.casefold()).strip()


def puntuar(texto, terms, pagina, paginas):
    t = normalizar(texto)
    score = sum((4 if len(term) > 8 else 2) * min(t.count(normalizar(term)), 4) for term in terms)
    if pagina in paginas:
        score += 3
    return score


def main():
    draft = BASE / 'preguntas_prueba_borrador.json'
    if not draft.exists():
        raise SystemExit(f'No se encuentra {draft}. Conserva el JSON que ya tienes en rag/evaluacion/.')
    preguntas = json.loads(draft.read_text(encoding='utf-8-sig'))
    if isinstance(preguntas, dict):
        preguntas = preguntas.get('preguntas', [])
    por_id = {p['id']:p for p in preguntas}
    faltan = set(CONFIG) - set(por_id)
    if faltan:
        raise SystemExit(f'Faltan preguntas en JSON: {sorted(faltan)}')
    conn_string = os.getenv('PG_CONNECTION_STRING')
    if not conn_string:
        raise SystemExit('Falta PG_CONNECTION_STRING en back/pass.env')
    with psycopg2.connect(conn_string) as db:
        db.set_session(readonly=True)
        with db.cursor() as cur:
            cur.execute('''SELECT id_fragmento, fuente, numero_fragmento, metadatos->>'pagina', texto
                           FROM rag_fragmentos WHERE tipo='guia' AND estado='publicada' ''')
            filas = cur.fetchall()
    fuentes = {p['fuente_esperada'] for p in (por_id[i] for i in CONFIG)}
    disponibles = {f[1] for f in filas}
    no_hay = fuentes - disponibles
    if no_hay:
        raise SystemExit(f'Fuentes no encontradas en Neon: {sorted(no_hay)}')
    carpeta = BASE / 'resultados'
    carpeta.mkdir(parents=True, exist_ok=True)
    informe = ['# Búsqueda complementaria de fragmentos — punto 7', '',
               'Candidatos **NO validados**. Revisar su contenido antes de añadirlos a fragmentos_relevantes.',
               'Solo se consultaron guías publicadas; no se accedió a historias clínicas.', '']
    salida = []
    for id_pregunta, cfg in CONFIG.items():
        p = por_id[id_pregunta]
        candidatos_anteriores = {c['id_fragmento'] for c in p.get('candidatos_para_revision', [])}
        candidatos = []
        for fid, fuente, nfrag, pagina_raw, texto in filas:
            if fuente != p['fuente_esperada']:
                continue
            try: pagina = int(pagina_raw)
            except (ValueError,TypeError): pagina = None
            score = puntuar(texto, cfg['terminos'], pagina, cfg['paginas'])
            # No repetir los candidatos del primer informe, salvo si sirven como contexto al lado.
            if score > 0 and fid not in candidatos_anteriores:
                candidatos.append({'id_fragmento':fid, 'fuente':fuente, 'pagina':pagina,
                                   'numero_fragmento':nfrag, 'puntaje_busqueda':score, 'texto':texto})
        candidatos.sort(key=lambda x:(-x['puntaje_busqueda'], x['pagina'] if x['pagina'] is not None else 9999, x['numero_fragmento']))
        # Mantener 12 resultados como máximo por pregunta para que el informe sea revisable.
        top = candidatos[:12]
        salida.append({'id':id_pregunta, 'pregunta':p['pregunta'], 'fuente_esperada':p['fuente_esperada'],
                       'candidatos_nuevos':[{k:v for k,v in c.items() if k != 'texto'} for c in top]})
        informe += [f"## {id_pregunta} — {p['pregunta']}", '', f"**Fuente:** {p['fuente_esperada']}",
                    f"**Candidatos nuevos:** {len(top)}", '']
        for idx,c in enumerate(top,1):
            informe += [f"### {idx}. `{c['id_fragmento']}` — página {c['pagina']}, fragmento {c['numero_fragmento']}",
                        f"Puntaje de búsqueda orientativo: {c['puntaje_busqueda']} (no es relevancia)",
                        '', '**Relevante:** [ ] Sí  [ ] No  [ ] Revisar', '', '```text',
                        c['texto'].replace('```','` ` `'), '```', '']
        informe += ['---', '']
    ruta_md = carpeta / 'fragmentos_faltantes_para_revision.md'
    ruta_json = carpeta / 'candidatos_complementarios.json'
    ruta_md.write_text('\n'.join(informe),encoding='utf-8')
    ruta_json.write_text(json.dumps(salida,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Fragmentos de guías consultados: {len(filas)}')
    for e in salida: print(f"{e['id']}: {len(e['candidatos_nuevos'])} candidatos adicionales")
    print(f'Informe: {ruta_md}')
    print(f'Índice JSON: {ruta_json}')
    print('Los candidatos NO han sido validados ni añadidos al conjunto de evaluación.')

if __name__ == '__main__':
    main()
