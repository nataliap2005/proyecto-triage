"""Recuperación RAG: BM25, dense (pgvector) e híbrida RRF.

Por defecto SOLO consulta guías públicas. Las historias requieren un contexto
validado por el backend (AccesoClinico), nunca un seudónimo enviado por cliente.
Desde la raíz: python rag/recuperar.py --pregunta "¿Qué es el triaje?" --metodo hibrido
Dependencias: psycopg2-binary python-dotenv sentence-transformers rank-bm25
"""
from __future__ import annotations
import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE.parent / 'back' / 'pass.env', override=False)
MODELO = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
Metodo = Literal['bm25', 'dense', 'hibrido']

@dataclass(frozen=True)
class AccesoClinico:
    """Crear ÚNICAMENTE tras comprobar identidad, rol y relación con paciente en backend."""
    seudonimo_paciente: str
    id_encuentro: int | None = None


def _filtro(acceso: AccesoClinico | None):
    if acceso is None:
        return "tipo='guia' AND estado='publicada'", []
    if not re.fullmatch(r'pac-[a-f0-9]{32}', acceso.seudonimo_paciente):
        raise ValueError('Seudónimo de paciente inválido')
    if acceso.id_encuentro is not None and (type(acceso.id_encuentro) is not int or acceso.id_encuentro <= 0):
        raise ValueError('Encuentro inválido')
    condicion = "((tipo='guia' AND estado='publicada') OR (tipo='historia' AND estado='aprobado' AND paciente=%s"
    params = [acceso.seudonimo_paciente]
    if acceso.id_encuentro is not None:
        condicion += " AND (metadatos->>'id_encuentro')::integer=%s"
        params.append(acceso.id_encuentro)
    condicion += '))'
    return condicion, params


def _tokenizar(texto: str):
    return re.findall(r'\w+', texto.casefold(), flags=re.UNICODE)


def _conectar():
    import psycopg2
    cadena = os.getenv('PG_CONNECTION_STRING')
    if not cadena:
        raise RuntimeError('Falta PG_CONNECTION_STRING en back/pass.env')
    return psycopg2.connect(cadena)


def _filas_a_dict(cursor):
    columnas = [c[0] for c in cursor.description]
    return [dict(zip(columnas, row)) for row in cursor.fetchall()]


def _bm25(cur, pregunta, condicion, params, cantidad):
    from rank_bm25 import BM25Okapi
    cur.execute(f'''SELECT id_fragmento, id_documento, tipo, fuente, texto, metadatos
                    FROM rag_fragmentos WHERE {condicion}''', params)
    documentos = _filas_a_dict(cur)
    tokens = [_tokenizar(d['texto']) for d in documentos]
    consulta = _tokenizar(pregunta)
    if not documentos or not consulta or not any(tokens):
        return []
    puntajes = BM25Okapi(tokens).get_scores(consulta)
    orden = sorted(range(len(documentos)), key=lambda i: float(puntajes[i]), reverse=True)
    return [{**documentos[i], 'puntaje': float(puntajes[i])} for i in orden[:cantidad] if puntajes[i] > 0]


def _dense(cur, pregunta, condicion, params, cantidad, modelo):
    vector = modelo.encode(pregunta, normalize_embeddings=True)
    literal = '[' + ','.join(str(float(v)) for v in vector) + ']'
    cur.execute(f'''SELECT id_fragmento, id_documento, tipo, fuente, texto, metadatos,
                       1 - (embedding <=> %s::vector) AS puntaje
                    FROM rag_fragmentos WHERE {condicion} AND modelo_embedding=%s
                    ORDER BY embedding <=> %s::vector LIMIT %s''',
                [literal, *params, MODELO, literal, cantidad])
    return _filas_a_dict(cur)


def buscar(pregunta: str, metodo: Metodo = 'hibrido', top_k: int = 5,
           acceso: AccesoClinico | None = None) -> list[dict]:
    """Solo guías por defecto. AccesoClinico requiere autorización previa externa.

    La función no verifica tokens ni RBAC: el backend DEBE hacerlo antes de crear
    AccesoClinico. No exponer acceso ni seudónimos como parámetros del endpoint.
    """
    if not pregunta.strip() or len(pregunta) > 2000:
        raise ValueError('Pregunta vacía o demasiado larga (máximo 2000 caracteres)')
    if metodo not in ('bm25', 'dense', 'hibrido') or not 1 <= top_k <= 20:
        raise ValueError('Método o top_k inválido')
    condicion, params = _filtro(acceso)
    modelo = None
    if metodo != 'bm25':
        from sentence_transformers import SentenceTransformer
        modelo = SentenceTransformer(MODELO)
    with _conectar() as db:
        db.set_session(readonly=True)
        with db.cursor() as cur:
            if metodo == 'bm25':
                resultados = _bm25(cur, pregunta, condicion, params, top_k)
            elif metodo == 'dense':
                resultados = _dense(cur, pregunta, condicion, params, top_k, modelo)
            else:
                n = max(30, top_k * 4)
                lexical = _bm25(cur, pregunta, condicion, params, n)
                semantica = _dense(cur, pregunta, condicion, params, n, modelo)
                fusion = {}
                for lista in (lexical, semantica):
                    for posicion, doc in enumerate(lista, start=1):
                        clave = doc['id_fragmento']
                        if clave not in fusion:
                            fusion[clave] = {**doc, 'puntaje': 0.0}
                        fusion[clave]['puntaje'] += 1.0 / (60 + posicion)
                resultados = sorted(fusion.values(), key=lambda d: d['puntaje'], reverse=True)[:top_k]
    for r in resultados:
        r['puntaje'] = float(r['puntaje'])
    return resultados



def expandir_contexto(fragmentos: list[dict], acceso: AccesoClinico | None = None,
                     max_semillas: int = 3, max_fragmentos: int = 20) -> list[dict]:
    """Amplía resultados sin cambiar el ranking original de buscar().

    Incluye todos los bloques de la misma página y, para guías, hasta tres
    bloques de los extremos de las páginas contiguas. Cada consulta mantiene
    el filtro de autorización original; nunca cruza pacientes.
    """
    if not fragmentos:
        return []
    condicion, params = _filtro(acceso)
    salida = []
    vistos = set()

    def agregar(doc, origen):
        if doc['id_fragmento'] in vistos or len(salida) >= max_fragmentos:
            return
        nuevo = dict(doc)
        nuevo['origen_contexto'] = origen
        nuevo['puntaje'] = float(nuevo.get('puntaje') or 0)
        salida.append(nuevo)
        vistos.add(nuevo['id_fragmento'])

    # Mantener todos los resultados originales en su orden y con su puntuación.
    for doc in fragmentos:
        agregar(doc, 'recuperado')

    with _conectar() as db:
        db.set_session(readonly=True)
        with db.cursor() as cur:
            for semilla in fragmentos[:max_semillas]:
                if len(salida) >= max_fragmentos:
                    break
                cur.execute(f'''SELECT id_fragmento, id_documento, numero_fragmento,
                                      tipo, fuente, texto, metadatos
                               FROM rag_fragmentos
                               WHERE {condicion} AND id_documento=%s
                               ORDER BY numero_fragmento''', [*params, semilla['id_documento']])
                pagina = _filas_a_dict(cur)
                for vecino in pagina:
                    agregar(vecino, 'vecino')
                if semilla['tipo'] != 'guia':
                    continue
                meta = semilla.get('metadatos') or {}
                numero_pagina = meta.get('pagina')
                if not isinstance(numero_pagina, int):
                    continue
                # Solo páginas contiguas del mismo archivo, no documentos ajenos.
                for pagina_vecina, extremo in ((numero_pagina - 1, 'anterior'),
                                                (numero_pagina + 1, 'siguiente')):
                    if pagina_vecina < 1 or len(salida) >= max_fragmentos:
                        continue
                    cur.execute(f'''SELECT id_fragmento, id_documento, numero_fragmento,
                                          tipo, fuente, texto, metadatos
                                   FROM rag_fragmentos
                                   WHERE {condicion} AND tipo='guia' AND fuente=%s
                                     AND (metadatos->>'pagina')::integer=%s
                                   ORDER BY numero_fragmento''',
                                [*params, semilla['fuente'], pagina_vecina])
                    vecinos = _filas_a_dict(cur)
                    # Extremo final de la página previa / inicial de la siguiente.
                    candidatos = vecinos[-3:] if extremo == 'anterior' else vecinos[:3]
                    for vecino in candidatos:
                        agregar(vecino, 'vecino')
    return salida


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pregunta', required=True)
    parser.add_argument('--metodo', choices=['bm25', 'dense', 'hibrido'], default='hibrido')
    parser.add_argument('--top-k', type=int, default=5)
    args = parser.parse_args()
    # CLI intencionalmente solo permite guías: no es una vía de acceso a historias.
    resultados = buscar(args.pregunta, args.metodo, args.top_k)
    print(f'Fragmentos encontrados: {len(resultados)}')
    for i, doc in enumerate(resultados, 1):
        meta = doc['metadatos']
        print(f"\n{i}. {meta.get('titulo') or doc['fuente']} | página {meta.get('pagina', '-')} | score {doc['puntaje']:.4f}")
        print(doc['texto'][:350].replace('\n', ' '))

if __name__ == '__main__':
    main()
