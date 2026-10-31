"""Orquestación RAG. CLI de prueba: solo guías públicas.

python rag/motor.py --pregunta "¿Qué recomienda NICE para dolor torácico?"
El backend debe autenticar y autorizar ANTES de proporcionar AccesoClinico.
"""
from __future__ import annotations
import argparse
import json
try:
    from .recuperar import buscar, expandir_contexto, AccesoClinico
    from .cliente_llm import generar
except ImportError:
    from recuperar import buscar, expandir_contexto, AccesoClinico
    from cliente_llm import generar


def preguntar(pregunta: str, metodo: str = 'hibrido', top_k: int = 5,
             acceso: AccesoClinico | None = None) -> dict:
    fragmentos = buscar(pregunta, metodo=metodo, top_k=top_k, acceso=acceso)
    if not fragmentos:
        return {'respuesta': 'No hay información suficiente en las fuentes recuperadas para responder.',
                'fuentes': [], 'metodo': metodo, 'fragmentos_recuperados': 0}
    contexto = expandir_contexto(fragmentos, acceso=acceso)
    respuesta = generar(pregunta, contexto)
    fuentes = []
    for i, doc in enumerate(contexto, 1):
        meta = doc.get('metadatos') or {}
        fuentes.append({'cita': f'F{i}', 'id_fragmento': doc['id_fragmento'],
                        'tipo': doc['tipo'], 'fuente': doc['fuente'],
                        'titulo': meta.get('titulo'), 'pagina': meta.get('pagina'),
                        'url': meta.get('url'), 'puntaje': doc['puntaje'],
                        'origen_contexto': doc['origen_contexto']})
    return {'respuesta': respuesta, 'fuentes': fuentes,
            'metodo': metodo, 'fragmentos_recuperados': len(fragmentos),
            'fragmentos_contexto': len(contexto)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pregunta', required=True)
    parser.add_argument('--metodo', choices=['bm25', 'dense', 'hibrido'], default='hibrido')
    parser.add_argument('--top-k', type=int, default=5)
    args = parser.parse_args()
    # No se expone acceso clínico en CLI.
    print(json.dumps(preguntar(args.pregunta, args.metodo, args.top_k),
                     ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
