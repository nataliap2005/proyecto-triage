"""Indexa guías clínicas e historias sintéticas aprobadas en Neon/pgvector.

Desde la raíz de proyecto_triaje:
    pip install psycopg2-binary python-dotenv sentence-transformers
    python rag/indexar.py                 # valida y muestra una vista previa
    python rag/indexar.py --aplicar       # crea/reemplaza el índice RAG

Requiere back/pass.env con PG_CONNECTION_STRING.
No cambia las tablas clínicas. Los embeddings se calculan localmente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
RAIZ = BASE.parent
DATOS = BASE / 'documentos' / 'textos_extraidos'
MODELO = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
DIMENSION = 384
MAX_CARACTERES = 1100
SOLAPAMIENTO = 180

load_dotenv(RAIZ / 'back' / 'pass.env', override=False)


def cargar_jsonl(ruta: Path, tipo: str) -> list[dict]:
    if not ruta.is_file():
        raise FileNotFoundError(f'Falta el archivo {ruta}')
    resultado = []
    with ruta.open(encoding='utf-8') as f:
        for linea, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            try:
                doc = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f'JSON inválido en {ruta.name}, línea {linea}') from exc
            if not isinstance(doc, dict) or doc.get('tipo') != tipo or not isinstance(doc.get('texto'), str):
                raise ValueError(f'Documento inválido en {ruta.name}, línea {linea}')
            if not doc.get('id') or not doc['texto'].strip():
                raise ValueError(f'ID o texto vacío en {ruta.name}, línea {linea}')
            if tipo == 'guia':
                if doc.get('estado') != 'publicada' or not doc.get('fuente') or not isinstance(doc.get('pagina'), int):
                    raise ValueError(f'Guía sin fuente/página/estado válido en línea {linea}')
            else:
                if doc.get('estado') != 'aprobado' or not re.fullmatch(r'pac-[a-f0-9]{32}', str(doc.get('paciente', ''))):
                    raise ValueError(f'Historia sin aprobación o seudónimo válido en línea {linea}')
                if not isinstance(doc.get('id_encuentro'), int):
                    raise ValueError(f'Historia sin id_encuentro válido en línea {linea}')
            resultado.append(doc)
    if not resultado:
        raise ValueError(f'Archivo sin documentos: {ruta.name}')
    ids = [x['id'] for x in resultado]
    if len(ids) != len(set(ids)):
        raise ValueError(f'IDs duplicados en {ruta.name}')
    return resultado


def fragmentar(texto: str, max_chars: int = MAX_CARACTERES, solape: int = SOLAPAMIENTO) -> list[str]:
    """Cortes aproximados en espacios, con solape; cada página es un documento separado."""
    texto = re.sub(r'[ \t]+', ' ', texto).strip()
    if not texto:
        return []
    fragmentos = []
    inicio = 0
    while inicio < len(texto):
        fin = min(inicio + max_chars, len(texto))
        if fin < len(texto):
            corte = max(texto.rfind('\n', inicio + max_chars // 2, fin),
                        texto.rfind(' ', inicio + max_chars // 2, fin))
            if corte > inicio:
                fin = corte
        parte = texto[inicio:fin].strip()
        if parte:
            fragmentos.append(parte)
        if fin >= len(texto):
            break
        inicio = max(inicio + 1, fin - solape)
        while inicio < len(texto) and texto[inicio].isspace():
            inicio += 1
    return fragmentos


def construir_fragmentos(guias: list[dict], historias: list[dict]) -> list[dict]:
    filas = []
    for doc in guias + historias:
        tipo = doc['tipo']
        # Metadatos estrictamente permitidos: no copiar datos identificables por accidente.
        meta = ({'titulo': doc.get('titulo'), 'institucion': doc.get('institucion'),
                 'url': doc.get('url'), 'pagina': doc['pagina']}
                if tipo == 'guia' else {'id_encuentro': doc['id_encuentro']})
        for numero, parte in enumerate(fragmentar(doc['texto'])):
            filas.append({
                'id_fragmento': hashlib.sha256(f"{doc['id']}:{numero}".encode()).hexdigest(),
                'id_documento': doc['id'], 'numero_fragmento': numero,
                'tipo': tipo, 'estado': doc['estado'],
                'paciente': doc.get('paciente') if tipo == 'historia' else None,
                'fuente': doc['fuente'], 'texto': parte, 'metadatos': meta,
            })
    return filas


def verificar_ocr():
    ruta = DATOS / 'reporte_extraccion.json'
    if not ruta.exists():
        print('Aviso: no existe reporte_extraccion.json; verifica manualmente las páginas de los PDF.')
        return
    reporte = json.loads(ruta.read_text(encoding='utf-8'))
    pendientes = reporte.get('paginas_requieren_revision_ocr', {})
    cantidad = sum(len(v) for v in pendientes.values())
    if cantidad:
        print(f'Aviso: {cantidad} páginas pendientes de OCR/revisión; extraer_pdfs.py ya las excluyó del JSONL.')


def aplicar(filas: list[dict], lote: int = 32) -> None:
    import psycopg2
    from psycopg2.extras import execute_values
    from sentence_transformers import SentenceTransformer

    cadena = os.getenv('PG_CONNECTION_STRING')
    if not cadena:
        raise SystemExit('Falta PG_CONNECTION_STRING en back/pass.env')
    print(f'Cargando modelo local: {MODELO}')
    modelo = SentenceTransformer(MODELO)
    if modelo.get_sentence_embedding_dimension() != DIMENSION:
        raise RuntimeError('La dimensión del modelo no coincide con la tabla vectorial.')

    # Primero calcular todos los vectores. Si falla, no tocamos el índice anterior.
    vectores = modelo.encode([x['texto'] for x in filas], batch_size=lote,
                             normalize_embeddings=True, show_progress_bar=True)
    if len(vectores) != len(filas):
        raise RuntimeError('No se generó un vector para cada fragmento')

    with psycopg2.connect(cadena) as db:
        with db.cursor() as cur:
            cur.execute('CREATE EXTENSION IF NOT EXISTS vector')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS rag_fragmentos (
                    id_fragmento TEXT PRIMARY KEY,
                    id_documento TEXT NOT NULL,
                    numero_fragmento INTEGER NOT NULL,
                    tipo TEXT NOT NULL CHECK (tipo IN ('guia','historia')),
                    estado TEXT NOT NULL,
                    paciente TEXT,
                    fuente TEXT NOT NULL,
                    texto TEXT NOT NULL,
                    metadatos JSONB NOT NULL,
                    embedding VECTOR(384) NOT NULL,
                    modelo_embedding TEXT NOT NULL,
                    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(id_documento, numero_fragmento),
                    CHECK ((tipo='guia' AND estado='publicada' AND paciente IS NULL)
                        OR (tipo='historia' AND estado='aprobado' AND paciente IS NOT NULL))
                )
            ''')
            # Reemplazo atómico del corpus: si ocurre un error, se revierte todo.
            cur.execute('DELETE FROM rag_fragmentos')
            for i in range(0, len(filas), lote):
                grupo = filas[i:i+lote]
                valores = []
                for fila, vector in zip(grupo, vectores[i:i+lote]):
                    valores.append((fila['id_fragmento'], fila['id_documento'],
                                    fila['numero_fragmento'], fila['tipo'], fila['estado'],
                                    fila['paciente'], fila['fuente'], fila['texto'],
                                    json.dumps(fila['metadatos'], ensure_ascii=False),
                                    '[' + ','.join(str(float(v)) for v in vector) + ']', MODELO))
                execute_values(cur, '''
                    INSERT INTO rag_fragmentos
                    (id_fragmento,id_documento,numero_fragmento,tipo,estado,paciente,
                     fuente,texto,metadatos,embedding,modelo_embedding)
                    VALUES %s
                ''', valores, template='(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector,%s)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_rag_tipo_paciente ON rag_fragmentos (tipo,paciente)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_rag_doc ON rag_fragmentos (id_documento)')
            cur.execute('SELECT tipo, COUNT(*) FROM rag_fragmentos GROUP BY tipo ORDER BY tipo')
            resumen = cur.fetchall()
    print('Indexación confirmada en Neon:', dict(resumen))
    print('AVISO: recuperar.py debe exigir autenticación y filtro por paciente para historias.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aplicar', action='store_true', help='Genera embeddings y escribe en Neon')
    parser.add_argument('--lote', type=int, default=32, help='Tamaño de lote de embeddings')
    args = parser.parse_args()
    if args.lote < 1:
        parser.error('--lote debe ser mayor que cero')
    guias = cargar_jsonl(DATOS / 'guias.jsonl', 'guia')
    historias = cargar_jsonl(DATOS / 'historias_aprobadas.jsonl', 'historia')
    verificar_ocr()
    filas = construir_fragmentos(guias, historias)
    print(f'Documentos: {len(guias)} páginas de guías y {len(historias)} historias aprobadas')
    print('Fragmentos:', dict(Counter(x['tipo'] for x in filas)))
    print(f'Modelo: {MODELO}; dimensión: {DIMENSION}')
    if not args.aplicar:
        print('VISTA PREVIA: no se escribió nada en Neon. Ejecuta con --aplicar para indexar.')
        return
    aplicar(filas, args.lote)


if __name__ == '__main__':
    main()
