"""Prueba rápida de recuperación para las 9 guías agregadas al corpus (R23).

Hace 2 preguntas por guía nueva (18 en total) y comprueba que entre los 3
fragmentos mejor clasificados (método híbrido) aparezca la guía esperada.
Solo consulta guías públicas: no usa Groq ni historias y no modifica Neon.

Desde la raíz del proyecto:
    python -m rag.evaluacion.prueba_guias_nuevas

Escribe rag/evaluacion/resultados/prueba_guias_nuevas.csv con el detalle.
Dependencias: las mismas de rag/recuperar.py.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from rag.recuperar import buscar

SALIDA = Path(__file__).resolve().parent / 'resultados' / 'prueba_guias_nuevas.csv'

# (inicio del nombre del PDF esperado, guía, pregunta). Todas son para adultos.
PREGUNTAS = [
    ('suspected-sepsis', 'NICE sepsis (NG253)',
     '¿Qué escala se recomienda para evaluar a adultos con sospecha de sepsis en un hospital de agudos?'),
    ('suspected-sepsis', 'NICE sepsis (NG253)',
     '¿Qué análisis de sangre se deben hacer a un adulto con sospecha de sepsis, como lactato y hemocultivo?'),
    ('head-injury', 'NICE traumatismo craneoencefálico (NG232)',
     '¿En qué casos se debe hacer una tomografía de cráneo en la primera hora en un adulto con traumatismo craneoencefálico?'),
    ('head-injury', 'NICE traumatismo craneoencefálico (NG232)',
     '¿Cómo se usa la escala de coma de Glasgow para valorar a un adulto con traumatismo craneoencefálico?'),
    ('pneumonia-diagnosis', 'NICE neumonía (NG250)',
     '¿Cómo se estratifica el riesgo de muerte en adultos con neumonía adquirida en la comunidad usando CRB65?'),
    ('pneumonia-diagnosis', 'NICE neumonía (NG250)',
     '¿Cuándo se recomienda hacer una radiografía de tórax de control después de una neumonía?'),
    ('hip-fracture', 'NICE fractura de cadera (CG124)',
     '¿En cuánto tiempo se debe operar una fractura de cadera después del ingreso?'),
    ('hip-fracture', 'NICE fractura de cadera (CG124)',
     '¿Qué condiciones corregibles, como anemia o anticoagulación, no deben retrasar la cirugía de cadera?'),
    ('low-back-pain', 'NICE dolor lumbar y ciática (NG59)',
     '¿Se recomienda pedir imágenes de rutina en el dolor lumbar en un entorno no especializado?'),
    ('low-back-pain', 'NICE dolor lumbar y ciática (NG59)',
     '¿Qué dice la guía sobre el uso de antiinflamatorios (AINE) en la ciática?'),
    ('fractures-noncomplex', 'NICE fracturas no complejas (NG38)',
     '¿Qué analgesia se recomienda para el dolor leve, moderado y severo en fracturas de huesos largos?'),
    ('fractures-noncomplex', 'NICE fracturas no complejas (NG38)',
     '¿Cómo se maneja el dolor y la inmovilización inicial en una fractura no compleja?'),
    ('acute-upper-gastrointestinal', 'NICE sangrado digestivo alto (CG141)',
     '¿Qué escalas de riesgo se usan en el sangrado digestivo alto, Blatchford antes de la endoscopia y Rockall después?'),
    ('acute-upper-gastrointestinal', 'NICE sangrado digestivo alto (CG141)',
     '¿En qué momento se debe hacer la endoscopia a un paciente con sangrado digestivo alto?'),
    ('acute-coronary', 'NICE síndromes coronarios agudos (NG185)',
     '¿Qué dosis de aspirina se da a un paciente con infarto con elevación del ST?'),
    ('acute-coronary', 'NICE síndromes coronarios agudos (NG185)',
     '¿Cuándo se hace un electrocardiograma después de la fibrinólisis en un infarto?'),
    ('gpc-profesionales', 'Minsalud GPC ACV isquémico (Guía 54)',
     '¿Qué es la escala NIHSS y para qué se usa en el ataque cerebrovascular?'),
    ('gpc-profesionales', 'Minsalud GPC ACV isquémico (Guía 54)',
     '¿Qué tratamientos de reperfusión existen en el ACV isquémico, como la trombolisis intravenosa?'),
]


def main() -> None:
    filas = []
    aciertos_top1 = 0
    aciertos_top3 = 0
    for esperado, guia, pregunta in PREGUNTAS:
        resultados = buscar(pregunta, 'hibrido', 3)
        fuentes = [r['fuente'] for r in resultados]
        pos = next((i for i, f in enumerate(fuentes, 1) if f.startswith(esperado)), None)
        aciertos_top1 += int(pos == 1)
        aciertos_top3 += int(pos is not None)
        marca = 'OK ' if pos else 'FALLA'
        print(f'{marca} [{guia}] posición de la guía esperada: {pos or "no está en el top 3"}')
        print(f'      {pregunta}')
        if not pos:
            print(f'      Top 3 devolvió: {[f[:40] for f in fuentes]}')
        filas.append({
            'guia_esperada': guia, 'pregunta': pregunta,
            'posicion_guia_esperada': pos or '',
            'acierto_top3': int(pos is not None),
            'fuentes_top3': ' | '.join(fuentes),
        })
    total = len(PREGUNTAS)
    print(f'\nGuía esperada en el top 1: {aciertos_top1}/{total}')
    print(f'Guía esperada en el top 3: {aciertos_top3}/{total}')
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with SALIDA.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
        w.writerow({'guia_esperada': 'RESUMEN', 'pregunta': datetime.now(timezone.utc).isoformat(),
                    'posicion_guia_esperada': '', 'acierto_top3': f'{aciertos_top3}/{total}',
                    'fuentes_top3': f'top1={aciertos_top1}/{total}'})
    print(f'Detalle guardado en {SALIDA}')


if __name__ == '__main__':
    main()
