"""Prepara el contexto 2 del RAG desde Neon, sin alterar registros clínicos.

Requisitos: pip install psycopg2-binary python-dotenv
Configuración: back/pass.env (PG_CONNECTION_STRING y SEUDONIMO_SECRETO).

Desde la raíz del proyecto:
    python rag/preparar_historias.py --confirmar-revision

La migración 010 crea encuentros.aprobado_rag (FALSE por defecto).
Este script NO aprueba encuentros; únicamente lee los marcados TRUE.
Solo exporta pacientes con origen='sintetico'. La confirmación significa
que un responsable ya revisó que los textos sintéticos no contienen datos
identificables. Los detectores automáticos son controles adicionales,
no una garantía de anonimización.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

BASE = Path(__file__).resolve().parent
RAIZ = BASE.parent
SALIDA = BASE / 'documentos' / 'textos_extraidos' / 'historias_aprobadas.jsonl'

# Misma ubicación de variables utilizada por back/core/config.py.
load_dotenv(RAIZ / 'back' / 'pass.env', override=False)


def seudonimo(documento: int, secreto: str) -> str:
    firma = hmac.new(secreto.encode('utf-8'), str(documento).encode('utf-8'), hashlib.sha256).hexdigest()
    return 'pac-' + firma[:32]


def comprobar_identificadores(texto: str, identificadores: list[str]) -> None:
    """Canario conservador: detiene la exportación ante coincidencias sospechosas."""
    for identificador in identificadores:
        identificador = str(identificador).strip()
        if identificador and re.search(r'(?<!\w)' + re.escape(identificador) + r'(?!\w)', texto, re.I):
            raise ValueError('Canario: identificador conocido presente en el texto clínico')
    patrones = (
        r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b',
        r'\b(?:\+?57[\s-]?)?3\d{9}\b',
        r'\b(?:CC|C\.C\.|cédula|documento)\s*[:#-]?\s*\d{6,12}\b',
    )
    if any(re.search(p, texto, re.I) for p in patrones):
        raise ValueError('Canario: posible dato personal en texto clínico')


def obtener_historia(cur, id_encuentro: int, id_paciente: int) -> dict:
    cur.execute('''
        SELECT motivo_consulta, nivel_triage, dolor_escala,
               observaciones_triage, observaciones_generales
        FROM encuentros
        WHERE id_encuentro = %s AND id_paciente = %s
          AND aprobado_rag IS TRUE AND is_deleted IS FALSE
    ''', (id_encuentro, id_paciente))
    encuentro = cur.fetchone()
    if encuentro is None:
        raise ValueError('Encuentro no autorizado durante la lectura')
    cur.execute('''
        SELECT tipo_nota, contenido FROM notas_clinicas
        WHERE id_encuentro = %s AND is_deleted IS FALSE
        ORDER BY fecha_hora, id_nota
    ''', (id_encuentro,))
    notas = cur.fetchall()
    cur.execute('''
        SELECT nombre, valor_numerico, valor_texto, unidad FROM observaciones
        WHERE id_encuentro = %s AND is_deleted IS FALSE
        ORDER BY fecha_hora_observacion, id_observacion
    ''', (id_encuentro,))
    observaciones = cur.fetchall()
    cur.execute('''
        SELECT descripcion, codigo_cie10, tipo FROM diagnosticos
        WHERE id_encuentro = %s AND is_deleted IS FALSE
        ORDER BY fecha_diagnostico, id_diagnostico
    ''', (id_encuentro,))
    diagnosticos = cur.fetchall()
    return {'encuentro': encuentro, 'notas': notas,
            'observaciones': observaciones, 'diagnosticos': diagnosticos}


def redactar_historia(datos: dict) -> str:
    e = datos['encuentro']
    lineas = [f"Motivo de consulta: {e['motivo_consulta']}"]
    for campo, etiqueta in (
        ('nivel_triage', 'Nivel de triaje'),
        ('dolor_escala', 'Escala de dolor'),
        ('observaciones_triage', 'Observaciones de triaje'),
        ('observaciones_generales', 'Observaciones generales'),
    ):
        if e[campo] is not None:
            lineas.append(f'{etiqueta}: {e[campo]}')
    for n in datos['notas']:
        lineas.append(f"Nota {n['tipo_nota']}: {n['contenido']}")
    for o in datos['observaciones']:
        valor = o['valor_numerico'] if o['valor_numerico'] is not None else o['valor_texto']
        lineas.append(f"Observación {o['nombre']}: {valor} {o['unidad'] or ''}".strip())
    for d in datos['diagnosticos']:
        lineas.append(f"Diagnóstico {d['tipo']}: {d['descripcion']} ({d['codigo_cie10'] or 'sin CIE10'})")
    return '\n'.join(lineas)


def ejecutar(confirmar_revision: bool) -> None:
    if not confirmar_revision:
        raise SystemExit('Falta --confirmar-revision: revise primero los textos sintéticos y su autorización.')
    conexion = os.getenv('PG_CONNECTION_STRING')
    secreto = os.getenv('SEUDONIMO_SECRETO')
    if not conexion or not secreto:
        raise SystemExit('Faltan PG_CONNECTION_STRING o SEUDONIMO_SECRETO en back/pass.env.')

    salida = []
    with psycopg2.connect(conexion) as db:
        db.set_session(readonly=True)
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('''
                SELECT e.id_encuentro, e.id_paciente,
                       p.nombres, p.apellidos, p.telefono, p.direccion
                FROM encuentros e
                JOIN pacientes p ON p.numero_documento_paciente = e.id_paciente
                WHERE e.aprobado_rag IS TRUE
                  AND e.is_deleted IS FALSE
                  AND p.is_deleted IS FALSE
                  AND p.origen = 'sintetico'
                ORDER BY e.id_encuentro
            ''')
            autorizados = cur.fetchall()
            for a in autorizados:
                datos = obtener_historia(cur, a['id_encuentro'], a['id_paciente'])
                texto = redactar_historia(datos)
                # Se bloquea el lote completo si se detecta algún identificador.
                comprobar_identificadores(texto, [
                    str(a['id_paciente']), a['nombres'], a['apellidos'],
                    a['telefono'] or '', a['direccion'] or '',
                ])
                salida.append({
                    'id': f"historia:{a['id_encuentro']}",
                    'tipo': 'historia', 'estado': 'aprobado',
                    'paciente': seudonimo(a['id_paciente'], secreto),
                    'id_encuentro': a['id_encuentro'],
                    'fuente': 'PostgreSQL/historia_clinica',
                    'texto': texto,
                })

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    temporal = SALIDA.with_suffix('.jsonl.tmp')
    try:
        with temporal.open('w', encoding='utf-8') as archivo:
            for historia in salida:
                archivo.write(json.dumps(historia, ensure_ascii=False, default=str) + '\n')
        temporal.replace(SALIDA)
    finally:
        temporal.unlink(missing_ok=True)
    print(f'Historias sintéticas autorizadas exportadas: {len(salida)}')
    print(f'Archivo: {SALIDA}')
    if not salida:
        print('No hay encuentros sintéticos aprobados. La salida está vacía; no se aprobó nada automáticamente.')
    print('ATENCIÓN: antes de consultar este corpus, el endpoint debe aplicar RBAC y filtros por paciente.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirmar-revision', action='store_true',
                        help='Confirma revisión humana previa de desidentificación de datos sintéticos')
    args = parser.parse_args()
    ejecutar(args.confirmar_revision)
