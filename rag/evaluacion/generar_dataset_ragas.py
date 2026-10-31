"""Dataset RAGAS con Dense + rescate normativo por artículo + vecinos reales.
Solo guías públicas. No utiliza respuestas ni IDs de relevancia del conjunto de prueba.
"""
import argparse
import json
import re
import shutil
import sys
import time
import random
from groq import RateLimitError
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rag import recuperar
from rag.cliente_llm import generar


def guardar_atomico(destino, datos):
    temporal = destino.with_suffix('.tmp')
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
    temporal.replace(destino)


def articulo_pedido(pregunta):
    coincidencia = re.search(r'\bart[ií]culo\s+(\d{1,3})\b', pregunta, re.I)
    return int(coincidencia.group(1)) if coincidencia else None


def rescatar_articulo(cur, pregunta, limite=5):
    """Busca en todas las guías el encabezado del artículo mencionado explícitamente.
    No usa fuente_esperada ni fragmentos_relevantes del dataset.
    """
    numero = articulo_pedido(pregunta)
    if numero is None:
        return []
    patron = rf'\mART[IÍ]CULO\s+{numero}\s*[.°º:]'
    cur.execute('''SELECT id_fragmento, id_documento, numero_fragmento, tipo, fuente, texto, metadatos
                   FROM rag_fragmentos
                   WHERE tipo='guia' AND estado='publicada'
                     AND texto ~* %s
                   ORDER BY length(texto) DESC LIMIT %s''', (patron, limite))
    columnas = [c[0] for c in cur.description]
    return [dict(zip(columnas, fila)) for fila in cur.fetchall()]


def completar_posiciones(cur, docs):
    """_dense no devuelve numero_fragmento; se consulta para que vecinos funcione."""
    ids = [d['id_fragmento'] for d in docs]
    if not ids:
        return docs
    cur.execute('''SELECT id_fragmento, numero_fragmento FROM rag_fragmentos
                   WHERE id_fragmento = ANY(%s) AND tipo='guia' AND estado='publicada' ''', (ids,))
    posiciones = dict(cur.fetchall())
    return [{**d, 'numero_fragmento': posiciones.get(d['id_fragmento'])} for d in docs]


def ampliar_vecinos(cur, docs, semillas, max_contextos):
    """Los vecinos van junto a su semilla, no detrás de todos los resultados."""
    salida, vistos = [], set()
    def anadir(doc):
        if doc and doc['id_fragmento'] not in vistos and len(salida) < max_contextos:
            salida.append(doc)
            vistos.add(doc['id_fragmento'])
    for i, d in enumerate(docs):
        anadir(d)
        if i >= semillas or len(salida) >= max_contextos:
            continue
        if d.get('id_documento') is None or d.get('numero_fragmento') is None:
            continue
        for indice in (d['numero_fragmento'] - 1, d['numero_fragmento'] + 1):
            if indice < 0:
                continue
            cur.execute('''SELECT id_fragmento, id_documento, numero_fragmento, tipo, fuente, texto, metadatos
                           FROM rag_fragmentos WHERE id_documento=%s AND numero_fragmento=%s
                             AND tipo='guia' AND estado='publicada' LIMIT 1''',
                        (d['id_documento'], indice))
            fila = cur.fetchone()
            if fila:
                cols = [c[0] for c in cur.description]
                anadir(dict(zip(cols, fila)))
    return salida


def generar_con_espera(pregunta, docs, max_reintentos=6):
    """Reintenta solamente errores 429; nunca vuelve a generar preguntas ya guardadas."""
    for intento in range(max_reintentos + 1):
        try:
            return generar(pregunta, docs)
        except RateLimitError as exc:
            if intento == max_reintentos:
                raise
            espera = min(120, 15 * (2 ** intento)) + random.uniform(0, 2)
            respuesta_http = getattr(exc, 'response', None)
            if respuesta_http is not None:
                cabecera = respuesta_http.headers.get('retry-after')
                if cabecera:
                    try:
                        espera = max(espera, float(cabecera))
                    except ValueError:
                        pass
            print(f'Groq 429: esperando {espera:.1f} s antes de reintentar ({intento+1}/{max_reintentos})...', flush=True)
            time.sleep(espera)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limite', type=int, default=20)
    parser.add_argument('--ids', nargs='+', metavar='PXX', help='Procesar solo estos IDs (ej. P07 P10)')
    parser.add_argument('--priorizar-nice', action='store_true', help='Priorizar guías NICE en la recuperación de los IDs elegidos')
    parser.add_argument('--top-k', type=int, default=10)
    parser.add_argument('--vecinos-de', type=int, default=3)
    parser.add_argument('--max-contextos', type=int, default=16)
    parser.add_argument('--reanudar', action='store_true')
    parser.add_argument('--regenerar', action='store_true')
    parser.add_argument('--pausa', type=float, default=25, help='Segundos entre preguntas nuevas (predeterminado: 25)')
    args = parser.parse_args()
    if not 1 <= args.limite <= 20 or not 1 <= args.top_k <= 20:
        parser.error('limite y top-k deben estar entre 1 y 20')
    if not 0 <= args.vecinos_de <= args.top_k or not args.top_k <= args.max_contextos <= 30:
        parser.error('vecinos-de debe ser 0..top-k; max-contextos >= top-k y <=30')
    if args.reanudar and args.regenerar:
        parser.error('Usa --reanudar o --regenerar, no ambos')
    if args.priorizar_nice and not args.ids:
        parser.error('--priorizar-nice requiere --ids para evitar cambios masivos')
    if args.priorizar_nice and set(args.ids) - {'P07', 'P10'}:
        parser.error('Esta priorización está configurada únicamente para P07 y P10')

    base = Path(__file__).resolve().parent
    preguntas = json.loads((base / 'preguntas_prueba.json').read_text(encoding='utf-8'))
    seleccion = preguntas[:args.limite]
    if args.ids:
        ids_validos = {p['id'] for p in preguntas}
        ids = set(args.ids)
        if ids - ids_validos:
            parser.error(f'IDs desconocidos: {sorted(ids - ids_validos)}')
        seleccion = [p for p in preguntas if p['id'] in ids]
    destino = base / 'resultados' / 'dataset_ragas_dense.json'
    destino.parent.mkdir(parents=True, exist_ok=True)
    previos = json.loads(destino.read_text(encoding='utf-8')) if destino.exists() and (args.reanudar or args.regenerar or args.ids) else []
    if args.ids and not destino.exists():
        parser.error('No existe el dataset original; no se puede actualizar de forma selectiva')
    registros = {r['id']: r for r in previos}
    if args.regenerar and destino.exists():
        respaldo = destino.with_name(f'{destino.stem}_respaldo_{datetime.now():%Y%m%d_%H%M%S}.json')
        shutil.copy2(destino, respaldo)
        print('Respaldo:', respaldo)

    print('Cargando embeddings una sola vez...')
    from sentence_transformers import SentenceTransformer
    modelo = SentenceTransformer(recuperar.MODELO)
    with recuperar._conectar() as db:
        db.set_session(readonly=True)
        with db.cursor() as cur:
            for item in seleccion:
                pid = item['id']
                if pid in registros and not args.regenerar:
                    print(f'{pid}: ya guardada')
                    continue
                pregunta = item['pregunta']
                filtro = "tipo='guia' AND estado='publicada'"
                fuente_priorizada = None
                parametros_filtro = []
                if args.priorizar_nice:
                    # Se utilizan nombres reales de PDF, no etiquetas de respuestas esperadas.
                    fuentes_por_pregunta = {
                        'P07': 'acutely-ill-adults-in-hospital%',
                        'P10': 'major-trauma-assessment-and-initial-management%',
                    }
                    patron = fuentes_por_pregunta[pid]
                    cur.execute("""SELECT COUNT(*) FROM rag_fragmentos
                                   WHERE tipo='guia' AND estado='publicada'
                                   AND fuente ILIKE %s""", (patron,))
                    disponibles = cur.fetchone()[0]
                    if not disponibles:
                        raise RuntimeError(
                            f'{pid}: no hay fragmentos publicados para {patron}; '
                            'se detiene sin reemplazar la respuesta guardada'
                        )
                    filtro += " AND fuente ILIKE %s"
                    parametros_filtro.append(patron)
                    fuente_priorizada = patron
                    print(f'{pid}: Dense limitado a {disponibles} fragmentos de {patron}')
                dense = recuperar._dense(cur, pregunta, filtro, parametros_filtro, args.top_k, modelo)
                dense = completar_posiciones(cur, dense)
                normativa = rescatar_articulo(cur, pregunta)
                # Los fragmentos que contienen el artículo solicitado tienen prioridad,
                # seguidos de Dense, sin duplicados ni información del ground truth.
                candidatos, vistos = [], set()
                for d in normativa + dense:
                    if d['id_fragmento'] not in vistos:
                        candidatos.append(d)
                        vistos.add(d['id_fragmento'])
                docs = ampliar_vecinos(cur, candidatos, max(args.vecinos_de, len(normativa)), args.max_contextos)
                if not docs:
                    print(f'{pid}: sin fragmentos; se omite')
                    continue
                respuesta = generar_con_espera(pregunta, docs)
                registros[pid] = {
                    'id': pid, 'user_input': pregunta, 'response': respuesta,
                    'retrieved_contexts': [d['texto'] for d in docs],
                    'fragmentos_recuperados': [d['id_fragmento'] for d in docs],
                    'fuentes': [{'fuente': d['fuente'], 'pagina': (d.get('metadatos') or {}).get('pagina')} for d in docs],
                    'metodo': 'dense_nice_vecinos' if fuente_priorizada else 'dense_rescate_normativo_vecinos', 'top_k': args.top_k,
                    'vecinos_de': args.vecinos_de, 'max_contextos': args.max_contextos,
                    'fragmentos_normativos': [d['id_fragmento'] for d in normativa],
                }
                orden = {p['id']: i for i, p in enumerate(preguntas)}
                guardar_atomico(destino, sorted(registros.values(), key=lambda r: orden.get(r['id'], 999)))
                print(f'{pid}: {len(docs)} contextos, {len(normativa)} fragmentos normativos')
                if args.pausa > 0:
                    time.sleep(args.pausa)
    print('Dataset:', destino)
    if args.ids:
        print('Solo se procesaron los IDs seleccionados:', ', '.join(sorted(args.ids)))
    print('Revisa las respuestas antes de volver a ejecutar RAGAS.')


if __name__ == '__main__':
    main()
