"""Contexto 1: extracción trazable de guías clínicas PDF.

Instalación: pip install pymupdf
Uso: python rag/extraer_pdfs.py
No crea embeddings: entrega documentos JSONL para indexar.py.
"""
from __future__ import annotations
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import fitz

BASE = Path(__file__).resolve().parent
ENTRADA = BASE / 'documentos' / 'pdf_originales'
SALIDA = BASE / 'documentos' / 'textos_extraidos'
MIN_CARACTERES = 80

# Edita las fuentes si cambias el corpus. No se inventan títulos ni URLs.
CATALOGO = {
    'Resolución 5596 de 2015.pdf': {'titulo': 'Resolución 5596 de 2015', 'institucion': 'Ministerio de Salud y Protección Social (Colombia)', 'url': None},
    '9789240006331-spa.pdf': {'titulo': 'Atención básica de emergencia: abordaje de lesionados y enfermos agudos (OMS)', 'institucion': 'Organización Mundial de la Salud / CICR / IFEM', 'url': None},
    'recentonset-chest-pain-of-suspected-cardiac-origin-assessment-and-diagnosis-pdf-975751034821.pdf': {'titulo': 'Recent-onset chest pain of suspected cardiac origin (CG95)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/cg95'},
    'acutely-ill-adults-in-hospital-recognising-and-responding-to-deterioration-pdf-975500772037.pdf': {'titulo': 'Acutely ill adults in hospital (CG50)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/cg50'},
    'major-trauma-assessment-and-initial-management-pdf-1837400761285.pdf': {'titulo': 'Major trauma: assessment and initial management (NG39)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/ng39'},
    'suspected-sepsis-in-people-aged-16-or-over-recognition-assessment-and-early-management-pdf-66144015386053.pdf': {'titulo': 'Suspected sepsis in people aged 16 or over: recognition, assessment and early management (NG253)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/ng253'},
    'head-injury-assessment-and-early-management-pdf-66143892774085.pdf': {'titulo': 'Head injury: assessment and early management (NG232)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/ng232'},
    'pneumonia-diagnosis-and-management-pdf-66144010347205.pdf': {'titulo': 'Pneumonia: diagnosis and management (NG250)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/ng250'},
    'hip-fracture-management-35109449902789.pdf': {'titulo': 'Hip fracture: management (CG124)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/cg124'},
    'low-back-pain-and-sciatica-in-over-16s-assessment-and-management-1837521693637.pdf': {'titulo': 'Low back pain and sciatica in over 16s: assessment and management (NG59)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/ng59'},
    'fractures-noncomplex-assessment-and-management-pdf-1837399081669.pdf': {'titulo': 'Fractures (non-complex): assessment and management (NG38)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/ng38'},
    'acute-upper-gastrointestinal-bleeding-in-over-16s-management-35109565796293.pdf': {'titulo': 'Acute upper gastrointestinal bleeding in over 16s: management (CG141)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/cg141'},
    'acute-coronary-syndromespdf-66142023361477.pdf': {'titulo': 'Acute coronary syndromes (NG185)', 'institucion': 'NICE', 'url': 'https://www.nice.org.uk/guidance/ng185'},
    'gpc-profesionales-ataque-cerebro-vascular-isquemico.pdf': {'titulo': 'GPC para el diagnóstico, tratamiento y rehabilitación del episodio agudo del ataque cerebrovascular isquémico en mayores de 18 años (Guía No. 54, 2015), para profesionales', 'institucion': 'Ministerio de Salud y Protección Social (Colombia) / Colciencias', 'url': 'https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/DE/CA/gpc-profesionales-ataque-cerebro-vascular-isquemico.pdf'},
}


def limpiar_texto(texto: str) -> str:
    texto = unicodedata.normalize('NFKC', texto)
    texto = texto.replace('\x00', '')
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\n[ \t]*\n[ \t]*\n+', '\n\n', texto)
    return texto.strip()


def extraer_archivo(ruta: Path) -> tuple[list[dict], list[int]]:
    fuente = CATALOGO.get(ruta.name, {'titulo': ruta.stem, 'institucion': 'Por verificar', 'url': None})
    documentos, revisar = [], []
    with fitz.open(ruta) as pdf:
        for i, pagina in enumerate(pdf):
            texto = limpiar_texto(pagina.get_text('text', sort=True))
            if len(texto) < MIN_CARACTERES:
                revisar.append(i + 1)
                continue  # No indexar páginas sin texto legible; requieren OCR/revisión.
            documentos.append({
                'id': f'guia:{ruta.stem}:p{i+1}',
                'tipo': 'guia', 'estado': 'publicada', 'paciente': None,
                'fuente': ruta.name, 'titulo': fuente['titulo'],
                'institucion': fuente['institucion'], 'url': fuente['url'],
                'pagina': i + 1, 'texto': texto,
            })
    return documentos, revisar


def ejecutar() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(ENTRADA.glob('*.pdf'))
    if not pdfs:
        raise SystemExit(f'No hay PDF en {ENTRADA}. Copia allí las cinco guías.')
    if len(pdfs) < 5:
        raise SystemExit(f'Se requieren al menos cinco guías; encontradas: {len(pdfs)}')
    documentos, advertencias = [], {}
    for pdf in pdfs:
        paginas, revisar = extraer_archivo(pdf)
        documentos.extend(paginas)
        if revisar:
            advertencias[pdf.name] = revisar
        print(f'{pdf.name}: {len(paginas)} páginas con texto; {len(revisar)} para revisar/OCR')
    destino = SALIDA / 'guias.jsonl'
    with destino.open('w', encoding='utf-8') as f:
        for doc in documentos:
            f.write(json.dumps(doc, ensure_ascii=False) + '\n')
    manifiesto = {'generado_utc': datetime.now(timezone.utc).isoformat(), 'pdfs': [p.name for p in pdfs],
                  'paginas_exportadas': len(documentos), 'paginas_requieren_revision_ocr': advertencias}
    (SALIDA / 'reporte_extraccion.json').write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Generado: {destino}')
    if advertencias:
        print('ATENCIÓN: hay páginas sin texto suficiente; revisa reporte_extraccion.json antes de indexar.')


if __name__ == '__main__':
    ejecutar()
