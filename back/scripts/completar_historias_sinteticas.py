"""Completa 5 encuentros SINTÉTICOS para pruebas RAG, sin inventar hallazgos.

Desde back/:
  python scripts/completar_historias_sinteticas.py             # previsualizar
  python scripts/completar_historias_sinteticas.py --aplicar   # insertar

No cambia triage, signos vitales, antecedentes ni aprobado_rag.
No utiliza un LLM ni envía datos fuera de PostgreSQL.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

BACK = Path(__file__).resolve().parents[1]
load_dotenv(BACK / 'pass.env')
IDS = (459, 264, 265, 266, 267)
MARCA = '[CASO SINTETICO RAG - APOYO A PRUEBAS]'

# Solo se codifica el SINTOMA que ya figura en el motivo, nunca una enfermedad inferida.
SINTOMAS = [
    (r'dolor.{0,25}(pecho|torax|tórax)|dolor tor[aá]cico', 'R07.4', 'Dolor torácico, no especificado'),
    (r'dificultad respiratoria|disnea|falta de aire', 'R06.0', 'Disnea'),
    (r'dolor abdominal|dolor.{0,15}abdomen', 'R10.9', 'Dolor abdominal, no especificado'),
    (r'cefalea|dolor de cabeza', 'R51', 'Cefalea'),
    (r'fiebre|febril', 'R50.9', 'Fiebre, no especificada'),
    (r'tos', 'R05', 'Tos'),
    (r'mareo|v[eé]rtigo', 'R42', 'Mareo y desvanecimiento'),
    (r'n[aá]usea|v[oó]mito', 'R11', 'Náusea y vómito'),
]


def sintoma_del_motivo(motivo: str):
    for patron, codigo, descripcion in SINTOMAS:
        if re.search(patron, motivo, flags=re.IGNORECASE):
            return codigo, descripcion
    return None


def resumen_observaciones(cur, eid):
    cur.execute('''
        SELECT nombre, valor_numerico, valor_texto, unidad
        FROM observaciones
        WHERE id_encuentro=%s AND is_deleted=FALSE
        ORDER BY fecha_hora_observacion, id_observacion
        LIMIT 20
    ''', (eid,))
    datos = []
    for o in cur.fetchall():
        nombre = str(o['nombre'] or 'Observación').strip()
        valor = o['valor_numerico'] if o['valor_numerico'] is not None else o['valor_texto']
        if valor is None:
            continue
        datos.append(f"{nombre}: {valor} {o['unidad'] or ''}".strip())
    return datos


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--aplicar', action='store_true', help='Confirma inserciones en la base de datos')
    args = p.parse_args()
    dsn = os.getenv('PG_CONNECTION_STRING')
    if not dsn:
        sys.exit('ERROR: falta PG_CONNECTION_STRING en back/pass.env')

    with psycopg2.connect(dsn) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Una única transacción; se bloquean las filas para evitar carreras al insertar.
            cur.execute('''
                SELECT e.id_encuentro, e.id_paciente, e.motivo_consulta,
                       e.nivel_triage, e.medico_responsable, e.clasificado_por,
                       e.is_deleted, p.origen, p.is_deleted AS paciente_eliminado
                FROM encuentros e JOIN pacientes p
                  ON p.numero_documento_paciente=e.id_paciente
                WHERE e.id_encuentro=ANY(%s)
                ORDER BY e.id_encuentro FOR UPDATE OF e
            ''', (list(IDS),))
            encuentros = {e['id_encuentro']: e for e in cur.fetchall()}
            if set(encuentros) != set(IDS):
                raise RuntimeError(f'Faltan encuentros: {sorted(set(IDS)-set(encuentros))}. No se modificó nada.')
            for e in encuentros.values():
                if e['origen'] != 'sintetico' or e['is_deleted'] or e['paciente_eliminado']:
                    raise RuntimeError(f"Encuentro {e['id_encuentro']} no es sintético activo. Operación cancelada.")
                if not (e['motivo_consulta'] or '').strip():
                    raise RuntimeError(f"Encuentro {e['id_encuentro']} sin motivo. Operación cancelada.")

            # Autor existente y activo, con rol médico. No inventar IDs de usuarios.
            cur.execute('''
                SELECT u.numero_documento_usuario
                FROM usuarios u JOIN roles r ON r.id_rol=u.id_rol
                WHERE r.nombre='Medico' AND u.estado=TRUE AND u.is_deleted=FALSE
                ORDER BY u.numero_documento_usuario LIMIT 1
            ''')
            medico = cur.fetchone()
            if not medico:
                raise RuntimeError('No hay médico activo para registrar datos de prueba. No se modificó nada.')
            autor = medico['numero_documento_usuario']
            nuevas_notas = nuevas_dx = 0
            for eid in IDS:
                e = encuentros[eid]
                motivo = e['motivo_consulta'].strip()
                obs = resumen_observaciones(cur, eid)
                triage = e['nivel_triage']
                nota = (
                    f'{MARCA} Registro complementario de simulación académica. '
                    f'Motivo de consulta previamente registrado: {motivo}. '
                    f'Nivel de triaje registrado: {triage if triage is not None else "no documentado"}. '
                    f'Observaciones existentes: {"; ".join(obs) if obs else "sin observaciones registradas"}. '
                    'No se documentan examen físico, antecedentes, evolución ni hallazgos adicionales: '
                    'no constan en la fuente. Este texto no representa una valoración médica real.'
                )
                cur.execute('''
                    SELECT 1 FROM notas_clinicas
                    WHERE id_encuentro=%s AND is_deleted=FALSE AND contenido LIKE %s
                    LIMIT 1
                ''', (eid, MARCA + '%'))
                insertar_nota = cur.fetchone() is None
                dx = sintoma_del_motivo(motivo)
                insertar_dx = False
                if dx:
                    cur.execute('''
                        SELECT 1 FROM diagnosticos
                        WHERE id_encuentro=%s AND is_deleted=FALSE AND codigo_cie10=%s
                        LIMIT 1
                    ''', (eid, dx[0]))
                    insertar_dx = cur.fetchone() is None
                print(f'Encuentro {eid}: observaciones={len(obs)}, triaje={triage}, '
                      f'nota={"crear" if insertar_nota else "ya existe"}, '
                      f'diagnóstico sintomático={dx[0] if insertar_dx else "sin inserción"}')
                if args.aplicar:
                    if insertar_nota:
                        cur.execute('''
                            INSERT INTO notas_clinicas(id_encuentro,tipo_nota,contenido,registrado_por)
                            VALUES (%s,'nota_clinica',%s,%s)
                        ''', (eid, nota, autor))
                        nuevas_notas += 1
                    if insertar_dx:
                        # Se etiqueta como síntoma documentado, no diagnóstico etiológico confirmado.
                        cur.execute('''
                            INSERT INTO diagnosticos(id_encuentro,codigo_cie10,descripcion,
                                                     tipo,estado_clinico,registrado_por)
                            VALUES (%s,%s,%s,'principal','active',%s)
                        ''', (eid, dx[0], f'{dx[1]} (síntoma del motivo; caso sintético)', autor))
                        nuevas_dx += 1
            if args.aplicar:
                print(f'Guardado: {nuevas_notas} notas nuevas y {nuevas_dx} diagnósticos sintomáticos nuevos.')
                print('No se modificaron triaje, observaciones, antecedentes ni aprobado_rag.')
            else:
                conn.rollback()
                print('PREVISUALIZACIÓN: no se modificó la base. Ejecuta con --aplicar para guardar.')


if __name__ == '__main__':
    main()
