"""Prueba local sin red ni consumo de tokens para revisar el prompt del cliente Groq.
Ejecutar desde la raiz del repositorio: python prueba_privacidad_rag.py
Solo utiliza un nombre y un documento ficticios.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PREGUNTA = "¿Qué dice la guía sobre María Prueba, documento 9876543210?"
FRAGMENTOS = [{
    "fuente": "guia_de_prueba.pdf",
    "texto": "Los profesionales de salud deben proteger la confidencialidad.",
    "metadatos": {"titulo": "Guía de prueba", "pagina": 1},
}]
capturado = {}

class ChatCompletions:
    def create(self, **kwargs):
        capturado.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Respuesta de prueba [F1]"))])

class GroqFalso:
    def __init__(self, **kwargs):
        pass
    @property
    def chat(self):
        return SimpleNamespace(completions=ChatCompletions())

modulo_groq = SimpleNamespace(Groq=GroqFalso)

with patch.dict(os.environ, {"GROQ_API_KEY": "clave-ficticia-prueba"}):
    with patch.dict(sys.modules, {"groq": modulo_groq}):
        from rag.cliente_llm import generar
        respuesta = generar(PREGUNTA, FRAGMENTOS)

mensaje = capturado["messages"][1]["content"]
print("=== PRUEBA LOCAL DE PRIVACIDAD RAG (SIN LLAMAR A GROQ) ===")
print("Cliente simulado:", respuesta)
for nombre, dato in [("Nombre ficticio", "María Prueba"), ("Documento ficticio", "9876543210")]:
    encontrado = dato in mensaje
    print(f"{nombre}: {'FUGA DETECTADA' if encontrado else 'NO se encuentra en prompt'}")
print("CONCLUSIÓN:", "REQUIERE CORRECCIÓN" if ("María Prueba" in mensaje or "9876543210" in mensaje) else "No se detectaron los canarios de esta prueba")
