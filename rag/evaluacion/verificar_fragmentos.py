"""Genera un informe de revisión de fragmentos candidatos desde Neon.

Ejecutar desde la raíz del proyecto:
    python rag/evaluacion/verificar_fragmentos.py

No decide automáticamente la relevancia: esa decisión exige revisar los textos.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entrada', type=Path, default=BASE / 'preguntas_prueba_borrador.json')
    parser.add_argument('--salida', type=Path, default=BASE / 'resultados' / 'revision_fragmentos.md')
    args = parser.parse_args()

    load_dotenv(ROOT / 'back' / 'pass.env', override=False)
    conn_str = os.getenv('PG_CONNECTION_STRING')
    if not conn_str:
        raise SystemExit('Falta PG_CONNECTION_STRING en back/pass.env o en el entorno.')
    if not args.entrada.exists():
        raise SystemExit(f'No se encontró el borrador: {args.entrada}')

    preguntas = json.loads(args.entrada.read_text(encoding='utf-8'))
    if not isinstance(preguntas, list):
        raise SystemExit('El JSON debe contener una lista de preguntas.')

    ids = list(dict.fromkeys(
        c['id_fragmento'] for p in preguntas
        for c in p.get('candidatos_para_revision', [])
    ))
    if not ids:
        raise SystemExit('El JSON no contiene candidatos_para_revision.')

    with psycopg2.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT id_fragmento, fuente, metadatos->>'pagina' AS pagina,
                       numero_fragmento, texto
                FROM rag_fragmentos
                WHERE tipo='guia' AND estado='publicada'
                  AND id_fragmento = ANY(%s)
            ''', (ids,))
            filas = cur.fetchall()

    datos = {r[0]: {'fuente': r[1], 'pagina': r[2],
                    'numero_fragmento': r[3], 'texto': r[4]} for r in filas}
    lineas = [
        '# Revisión de fragmentos candidatos — RAG clínico',
        '',
        'Este documento contiene candidatos, **no fragmentos validados**.',
        'Revisa el texto completo y determina cuáles responden realmente cada pregunta.',
        'No uses las métricas hasta completar la referencia de relevancia.',
        '',
    ]
    pendientes = 0
    for p in preguntas:
        lineas.extend([f"## {p['id']} — {p['pregunta']}", '',
                       f"**Fuente esperada:** {p.get('fuente_esperada', 'No especificada')}", ''])
        for c in p.get('candidatos_para_revision', []):
            fid = c['id_fragmento']
            d = datos.get(fid)
            if not d:
                pendientes += 1
                lineas.extend([f'### {fid}', '', '**NO ENCONTRADO EN NEON**', ''])
                continue
            if d['fuente'] != p.get('fuente_esperada'):
                pendientes += 1
                lineas.extend([f'**ADVERTENCIA:** fuente distinta de la esperada: {d["fuente"]}', ''])
            lineas.extend([
                f"### Fragmento `{fid}` — página {d['pagina']}, número {d['numero_fragmento']}",
                '', '**¿Es relevante?** [ ] Sí  [ ] No  [ ] Revisar', '',
                '```text', d['texto'].replace('```', "'''"), '```', '',
            ])
        lineas.extend(['**Observaciones / otros fragmentos necesarios:**', '', '---', ''])

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text('\n'.join(lineas), encoding='utf-8')
    print(f'Preguntas: {len(preguntas)} | Candidatos únicos: {len(ids)} | Encontrados: {len(datos)}')
    print(f'Advertencias: {pendientes}')
    print(f'Informe creado: {args.salida}')
    print('IMPORTANTE: El informe NO valida relevancia automáticamente.')


if __name__ == '__main__':
    main()
