"""Diagnostica y selecciona hasta 10 candidatos sintéticos para RAG.

Desde back/: python scripts/seleccionar_encuentros_rag.py
No cambia la base de datos, no autoriza historias ni imprime datos personales.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg2
from psycopg2.extras import RealDictCursor
from core.config import PG_CONNECTION_STRING

with psycopg2.connect(PG_CONNECTION_STRING) as db:
    db.set_session(readonly=True)
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT COALESCE(p.origen, '(sin origen)') AS origen,
                   COUNT(DISTINCT p.numero_documento_paciente) AS pacientes,
                   COUNT(e.id_encuentro) AS encuentros
            FROM pacientes p
            LEFT JOIN encuentros e ON e.id_paciente = p.numero_documento_paciente
                 AND e.is_deleted IS FALSE
            WHERE p.is_deleted IS FALSE
            GROUP BY COALESCE(p.origen, '(sin origen)')
            ORDER BY origen
        """)
        print('Resumen de registros disponibles:')
        for r in cur.fetchall():
            print(f"  origen={r['origen']}: {r['pacientes']} pacientes, {r['encuentros']} encuentros")

        cur.execute("""
            SELECT e.id_encuentro,
                   CASE WHEN NULLIF(BTRIM(COALESCE(e.motivo_consulta, '')), '') IS NOT NULL THEN 1 ELSE 0 END AS motivo,
                   CASE WHEN e.nivel_triage BETWEEN 1 AND 5 THEN 1 ELSE 0 END AS triage,
                   (SELECT COUNT(*) FROM notas_clinicas n WHERE n.id_encuentro=e.id_encuentro AND n.is_deleted IS FALSE) AS notas,
                   (SELECT COUNT(*) FROM observaciones o WHERE o.id_encuentro=e.id_encuentro AND o.is_deleted IS FALSE) AS observaciones,
                   (SELECT COUNT(*) FROM diagnosticos d WHERE d.id_encuentro=e.id_encuentro AND d.is_deleted IS FALSE) AS diagnosticos
            FROM encuentros e
            JOIN pacientes p ON p.numero_documento_paciente=e.id_paciente
            WHERE p.origen='sintetico' AND p.is_deleted IS FALSE AND e.is_deleted IS FALSE
            ORDER BY e.id_encuentro
        """)
        filas = cur.fetchall()

candidatos = []
for r in filas:
    # Basta con información clínica en una o varias fuentes; no exigimos todas las tablas.
    puntaje = int(r['motivo']) + int(r['triage']) + min(int(r['notas']), 3) * 3 + min(int(r['observaciones']), 3) * 2 + min(int(r['diagnosticos']), 3) * 2
    if puntaje > 0:
        candidatos.append((puntaje, r))
candidatos.sort(key=lambda x: (-x[0], x[1]['id_encuentro']))
print(f'Encuentros sintéticos totales: {len(filas)}')
print(f'Encuentros sintéticos con algún dato clínico: {len(candidatos)}')
for puntaje, r in candidatos[:10]:
    print(f"  Encuentro {r['id_encuentro']}: motivo={bool(r['motivo'])}, triaje={bool(r['triage'])}, "
          f"notas={r['notas']}, observaciones={r['observaciones']}, diagnosticos={r['diagnosticos']}, puntaje={puntaje}")
if not candidatos:
    print('No hay candidatos sintéticos. Revisa el resumen por origen: podría no haber encuentros sintéticos.')
print('Solo diagnóstico y selección preliminar: NO se aprobó ni exportó ninguna historia.')
