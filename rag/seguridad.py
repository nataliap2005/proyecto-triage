"""R25: identificación conservadora y saneamiento de instrucciones maliciosas en texto no confiable."""
from __future__ import annotations
import re

# Clasificaciones deliberadamente limitadas; pueden escapar variantes novedosas.
PATRONES = (
    ('anular_instrucciones', re.compile(r'\b(?:ignora|ignor[ae]|olvida|desobedece|omite|descarta)\s+(?:(?:todas?|las?|los?|tus?|mis?|anteriores?|previas?|del\s+sistema)\s+){0,5}(?:instrucciones|reglas|pol[ií]ticas|restricciones|indicaciones|prompt)\b', re.I)),
    ('override_ingles', re.compile(r'\b(?:ignore|disregard|forget|override)\s+(?:(?:all|your|previous|prior|system|the)\s+){0,5}(?:instructions|rules|policies|prompt)\b', re.I)),
    ('suplantacion_rol', re.compile(r'\b(?:act[uú]a|comp[oó]rtate|hazte\s+pasar)\s+como\s+(?:administrador(?:a)?|system|desarrollador(?:a)?|root)\b', re.I)),
    ('suplantacion_marcador', re.compile(r'<\|(?:im_start|system|developer|endoftext)\|>|\[/?INST\]|\[/?SYS\]', re.I)),
    ('exfiltracion_masiva', re.compile(r'\b(?:muestra|lista|exporta|extrae|revela|entrega|descarga|env[ií]a(?:me)?|dame)\s+(?:(?:todos?|todas?|los|las|datos|registros|historiales|historias|de)\s+){0,6}(?:pacientes|historias\s+cl[ií]nicas|credenciales|contrase[nñ]as|tokens|documentos\s+de\s+identidad)\b', re.I)),
    ('sql_masivo', re.compile(r'\b(?:select\s+\*\s+from\s+(?:public\.)?(?:pacientes|usuarios)|drop\s+table\b|delete\s+from\s+(?:public\.)?(?:pacientes|usuarios))', re.I)),
)

def detectar_inyeccion(texto: str) -> str | None:
    """Señal de alta confianza; no usar como único control de autorización."""
    if not isinstance(texto, str):
        return None
    for codigo, patron in PATRONES:
        if patron.search(texto):
            return codigo
    return None


def sanear_fragmento(texto: str) -> str:
    """Quita líneas con instrucciones hostiles de documentos/observaciones antes de RAG.

    Se conserva evidencia clínica no maliciosa; la fuente se mantiene como dato,
    nunca se le otorga el rol de mensaje system/developer.
    """
    if not texto:
        return ''
    lineas = str(texto).splitlines()
    limpias = ['[Instrucción no confiable omitida]' if detectar_inyeccion(linea) else linea
               for linea in lineas]
    return '\n'.join(limpias)


