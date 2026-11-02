"""Orquestación RAG: recuperar -> (abstención) -> generar con citas.

CLI de prueba (solo guías públicas):
    python rag/motor.py --pregunta "¿Qué recomienda NICE para dolor torácico?"

El backend (back/routers/rag.py) autentica, autoriza y seudonimiza ANTES de
construir AccesoClinico. Este módulo nunca recibe el documento real del paciente.

Variables de entorno opcionales:
    RAG_METODO        dense | bm25 | hibrido   (dense ganó en la evaluación, ver docs/RAG.md)
    RAG_TOP_K         fragmentos recuperados (por defecto 5)
    RAG_MAX_CONTEXTO  fragmentos que viajan al LLM tras expandir vecinos (por defecto 8)
    RAG_UMBRAL_COS    similitud coseno mínima para no abstenerse (por defecto 0.35)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re

try:
    from .recuperar import buscar, expandir_contexto, AccesoClinico
    from .cliente_llm import generar
except ImportError:
    from recuperar import buscar, expandir_contexto, AccesoClinico
    from cliente_llm import generar

log = logging.getLogger('rag')
SIN_EVIDENCIA = 'No hay evidencia suficiente en las fuentes del sistema para responder esta pregunta.'
METODO_DEFECTO = os.getenv('RAG_METODO', 'dense')
TOP_K = int(os.getenv('RAG_TOP_K', '5'))
MAX_CONTEXTO = int(os.getenv('RAG_MAX_CONTEXTO', '8'))
# En la evaluación, el primer fragmento de las 20 preguntas clínicas tuvo coseno entre 0,60 y 0,78;
# una pregunta corta como "¿Qué es el triaje?" sacó 0,41. Confirmar que lo ajeno quede por debajo.
UMBRAL_COS = float(os.getenv('RAG_UMBRAL_COS', '0.35'))


def _es_limite(exc: Exception) -> bool:
    """Groq responde 429 cuando se agota el cupo de solicitudes o tokens por minuto/día."""
    texto = f'{type(exc).__name__} {exc}'.lower()
    return 'ratelimit' in texto or '429' in texto or 'rate limit' in texto


def _extractiva(contexto: list[dict], n: int = 3) -> str:
    """Respaldo sin LLM: frases textuales de los mejores fragmentos con su cita. No puede alucinar."""
    partes = []
    for i, doc in enumerate(contexto[:n], 1):
        texto = ' '.join(doc['texto'].split())
        recorte = texto[:320].rsplit(' ', 1)[0] + ('…' if len(texto) > 320 else '')
        partes.append(f'{recorte} [F{i}]')
    return '\n\n'.join(partes)


def normalizar_citas(texto: str) -> str:
    """Lleva cualquier formato de cita al estándar [F#].

    gpt-oss cita como 【F1†L6-L9】 o 【F1】; otros modelos como (F1) o [F1, F2].
    """
    texto = re.sub(r'【\s*(F\d+)[^】]*】', r'[\1]', texto)
    texto = re.sub(r'\((F\d+(?:\s*,\s*F\d+)*)\)', r'[\1]', texto)
    return texto


def _hay_evidencia(fragmentos: list[dict], metodo: str) -> bool:
    if not fragmentos:
        return False
    if metodo == 'dense':
        return fragmentos[0]['puntaje'] >= UMBRAL_COS
    return True  # bm25 ya descarta puntaje 0; en híbrido el RRF no es comparable con un umbral fijo


def preguntar(pregunta: str, metodo: str | None = None, top_k: int | None = None,
              acceso: AccesoClinico | None = None) -> dict:
    metodo = metodo or METODO_DEFECTO
    top_k = top_k or TOP_K
    fragmentos = buscar(pregunta, metodo=metodo, top_k=top_k, acceso=acceso)
    if not _hay_evidencia(fragmentos, metodo):
        return {'respuesta': SIN_EVIDENCIA, 'modo': 'abstencion', 'aviso': None, 'fuentes': [],
                'metodo': metodo, 'fragmentos_recuperados': len(fragmentos), 'fragmentos_contexto': 0}

    contexto = expandir_contexto(fragmentos, acceso=acceso, max_fragmentos=MAX_CONTEXTO)
    aviso = None
    try:
        respuesta, modo = normalizar_citas(generar(pregunta, contexto)), 'llm'
    except Exception as exc:  # noqa: BLE001 — cualquier fallo del LLM degrada a extractivo
        # La causa real va al log (consola del servidor), nunca al usuario: puede incluir detalles internos.
        log.warning('LLM no disponible, respuesta extractiva: %s: %s', type(exc).__name__, exc)
        respuesta, modo = _extractiva(contexto), 'extractivo'
        aviso = ('Se alcanzó el límite de uso del modelo de lenguaje; se muestran los fragmentos '
                 'textuales más relevantes. Intente de nuevo en unos minutos.'
                 if _es_limite(exc) else
                 'El modelo de lenguaje no está disponible; se muestran los fragmentos textuales más relevantes.')

    citadas = {int(n) for n in re.findall(r'F(\d+)', ' '.join(re.findall(r'\[(F\d+(?:\s*,\s*F\d+)*)\]', respuesta)))}
    fuentes = []
    for i, doc in enumerate(contexto, 1):
        meta = doc.get('metadatos') or {}
        fuentes.append({'cita': f'F{i}', 'citada': i in citadas,
                        'id_fragmento': doc['id_fragmento'], 'tipo': doc['tipo'],
                        'fuente': doc['fuente'], 'titulo': meta.get('titulo'),
                        'pagina': meta.get('pagina'), 'url': meta.get('url'),
                        'id_encuentro': meta.get('id_encuentro'),
                        'puntaje': round(doc['puntaje'], 4),
                        'origen_contexto': doc['origen_contexto'],
                        'extracto': ' '.join(doc['texto'].split())[:400]})
    return {'respuesta': respuesta, 'modo': modo, 'aviso': aviso, 'fuentes': fuentes,
            'metodo': metodo, 'fragmentos_recuperados': len(fragmentos),
            'fragmentos_contexto': len(contexto)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pregunta', required=True)
    parser.add_argument('--metodo', choices=['bm25', 'dense', 'hibrido'], default=None)
    parser.add_argument('--top-k', type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    # No se expone acceso clínico en CLI: solo guías.
    print(json.dumps(preguntar(args.pregunta, args.metodo, args.top_k), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
