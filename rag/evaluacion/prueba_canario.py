"""Prueba canario sobre el índice YA CARGADO en Neon (rag_fragmentos). Semana 12.

preparar_historias.py bloquea la exportación si detecta identificadores, pero esta prueba
revisa lo que realmente quedó indexado, por si alguien cargó datos por otra vía.

Desde la raíz del proyecto:
    python -m rag.evaluacion.prueba_canario

Comprueba:
  1. Ningún nombre, apellido, documento, teléfono ni dirección de la tabla
     pacientes aparece en el texto o metadatos de un fragmento.
  2. Ningún patrón de PII (correo, celular colombiano, "CC 123...") aparece en el índice.
  3. Solo hay guías 'publicada' sin paciente e historias 'aprobado' con seudónimo pac-<32 hex>.
  4. Filtro clínico: al buscar con el acceso de un paciente, nunca vuelve una historia de otro.
Sale con código 1 si algo falla (útil para el tester).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(RAIZ / 'back' / 'pass.env', override=False)

PATRONES = {
    'correo': r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b',
    'celular': r'\b(?:\+?57[\s-]?)?3\d{9}\b',
    'documento': r'\b(?:CC|C\.C\.|c[ée]dula|documento)\s*[:#-]?\s*\d{6,12}\b',
}


def _identificadores(cur) -> list[str]:
    cur.execute('''SELECT numero_documento_paciente::text, nombres, apellidos,
                          telefono, direccion FROM pacientes''')
    valores = set()
    for fila in cur.fetchall():
        for v in fila:
            v = (str(v).strip() if v is not None else '')
            # Nombres muy cortos ("Ana") generan falsos positivos con palabras clínicas: se exige >= 4.
            if len(v) >= 4:
                valores.add(v)
    return sorted(valores)


def main() -> int:
    import psycopg2
    cadena = os.getenv('PG_CONNECTION_STRING')
    if not cadena:
        print('Falta PG_CONNECTION_STRING en back/pass.env')
        return 2
    fallos: list[str] = []
    with psycopg2.connect(cadena) as db:
        db.set_session(readonly=True)
        with db.cursor() as cur:
            ids = _identificadores(cur)
            cur.execute('SELECT id_fragmento, tipo, estado, paciente, texto, metadatos FROM rag_fragmentos')
            fragmentos = cur.fetchall()

    print(f'Fragmentos revisados: {len(fragmentos)} · identificadores de pacientes: {len(ids)}')
    historias = [f for f in fragmentos if f[1] == 'historia']
    for id_frag, tipo, estado, paciente, texto, meta in fragmentos:
        contenido = texto + ' ' + json.dumps(meta or {}, ensure_ascii=False)
        # 1 y 2 solo aplican a historias: las guías públicas pueden traer correos o teléfonos institucionales.
        if tipo == 'historia':
            for ident in ids:
                if re.search(r'(?<!\w)' + re.escape(ident) + r'(?!\w)', contenido, re.I):
                    fallos.append(f'{id_frag[:12]}: identificador de paciente presente')
                    break
            for nombre, patron in PATRONES.items():
                if re.search(patron, contenido, re.I):
                    fallos.append(f'{id_frag[:12]}: patrón de {nombre}')
            if estado != 'aprobado' or not re.fullmatch(r'pac-[a-f0-9]{32}', paciente or ''):
                fallos.append(f'{id_frag[:12]}: historia no aprobada o sin seudónimo válido')
        elif tipo == 'guia' and (estado != 'publicada' or paciente is not None):
            fallos.append(f'{id_frag[:12]}: guía no publicada o con paciente')

    # 4. Filtro por paciente con la misma función que usa el endpoint (BM25: no carga el modelo).
    from rag.recuperar import AccesoClinico, buscar
    seudonimos = sorted({f[3] for f in historias})
    for alias in seudonimos[:5]:
        consulta = next(f[4] for f in historias if f[3] == alias)[:200]
        for r in buscar(consulta, metodo='bm25', top_k=20, acceso=AccesoClinico(alias)):
            if r['tipo'] == 'historia' and r['id_fragmento'] not in {f[0] for f in historias if f[3] == alias}:
                fallos.append(f'Filtro: la búsqueda de {alias[:12]} devolvió una historia de otro paciente')
    print(f'Filtro por paciente probado con {min(5, len(seudonimos))} seudónimos')

    if fallos:
        print(f'\nFALLÓ · {len(fallos)} problemas:')
        for f in fallos[:50]:
            print('  -', f)
        return 1
    print('OK · sin fugas de datos personales y filtros clínicos correctos')
    return 0


if __name__ == '__main__':
    sys.exit(main())
