"""Minimización de identificadores explícitos en consultas libres del RAG.

Control de defensa en profundidad: NO equivale a reconocimiento exhaustivo de PII.
Nunca usar esta función como sustituto de autorización y filtrado por paciente.
"""
from __future__ import annotations
import re

_REGLAS = (
    # Emails.
    (re.compile(r'(?<![\w.])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?!\w)', re.I), '[CORREO]'),
    # Campos identificados explícitamente (documento, cédula, CC, teléfono, etc.).
    (re.compile(r'\b(?:n[uú]mero\s+de\s+)?(?:documento|c[eé]dula|identificaci[oó]n|CC|TI|pasaporte)\s*(?:n[.º°o]*\s*)?(?:[:#=-]\s*|es\s+|del?\s+)?\d[\d.\s-]{5,16}\d\b', re.I), '[DOCUMENTO]'),
    (re.compile(r'\b(?:tel[eé]fono|celular|m[oó]vil|whatsapp)\s*(?:[:#=-]\s*|es\s+|del?\s+)?\+?\d[\d\s()-]{7,17}\d\b', re.I), '[TELÉFONO]'),
    # Secuencias numéricas largas aisladas (cédulas/teléfonos sin etiqueta).
    (re.compile(r'(?<!\w)\d{8,12}(?!\w)'), '[IDENTIFICADOR]'),
    # Nombres explícitamente precedidos de una etiqueta o una referencia a persona.
    (re.compile(r'\b(?:nombre(?:\s+completo)?|paciente(?:\s+llamad[oa])?|se\s+llama|sobre)\s*(?:[:=]\s*|es\s+|de\s+)?\s*(?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+){1,3}[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\b', re.I), '[PERSONA]'),
)


def proteger_texto(texto: str) -> str:
    """Reemplaza PII reconocible por marcadores; no registra el texto original."""
    resultado = texto
    for patron, sustituto in _REGLAS:
        resultado = patron.sub(sustituto, resultado)
    return resultado
