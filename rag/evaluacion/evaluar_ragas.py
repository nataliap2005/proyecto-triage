"""Evalúa RAGAS 0.2.x de forma secuencial, reanudable y con guardado incremental."""
import argparse
import csv
import json
import math
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / 'back' / 'pass.env', override=False)

METRICAS = ('faithfulness', 'answer_relevancy')


def numero(valor):
    try:
        n = float(valor)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def guardar(ruta, filas):
    temporal = ruta.with_suffix('.tmp')
    with temporal.open('w', newline='', encoding='utf-8-sig') as archivo:
        writer = csv.DictWriter(archivo, fieldnames=['id', *METRICAS])
        writer.writeheader()
        for fila in filas:
            writer.writerow({'id': fila['id'], **{m: fila.get(m, '') for m in METRICAS}})
    temporal.replace(ruta)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limite', type=int, default=20)
    parser.add_argument('--ids', nargs='+', help='Ejemplo: --ids P07 P10')
    parser.add_argument('--pausa', type=float, default=30, help='Segundos entre métricas')
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--reintentos', type=int, default=1)
    parser.add_argument('--reiniciar', action='store_true', help='Ignorar CSV parcial y recalcular')
    parser.add_argument('--reintentos-429', type=int, default=10, help='Reintentos automáticos por límite TPM')
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    origen = base / 'resultados' / 'dataset_ragas_dense.json'
    salida = base / 'resultados' / 'ragas_metricas_dense_progreso.csv'
    if not origen.exists():
        parser.error('No existe dataset_ragas_dense.json')
    datos = json.loads(origen.read_text(encoding='utf-8'))
    if not 1 <= args.limite <= len(datos):
        parser.error(f'--limite debe estar entre 1 y {len(datos)}')
    if args.pausa < 0 or args.timeout < 1 or args.max_tokens < 1 or args.reintentos < 0 or args.reintentos_429 < 0:
        parser.error('Parámetros numéricos fuera de rango')
    seleccion = datos[:args.limite]
    if args.ids:
        buscados = set(args.ids)
        seleccion = [r for r in seleccion if r['id'] in buscados]
        faltantes = buscados - {r['id'] for r in seleccion}
        if faltantes:
            parser.error('IDs fuera de la selección: ' + ', '.join(sorted(faltantes)))
    if not os.getenv('GROQ_API_KEY'):
        parser.error('Falta GROQ_API_KEY en back/pass.env')

    # CSV nuevo: no sobrescribe ragas_metricas_dense.csv de la ejecución anterior.
    anteriores = {}
    if salida.exists() and not args.reiniciar:
        with salida.open(newline='', encoding='utf-8-sig') as archivo:
            for fila in csv.DictReader(archivo):
                anteriores[fila['id']] = {m: numero(fila.get(m)) for m in METRICAS}
    filas = {r['id']: {'id': r['id'], **anteriores.get(r['id'], {})} for r in seleccion}

    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.run_config import RunConfig
    from langchain_groq import ChatGroq
    from langchain_huggingface import HuggingFaceEmbeddings
    from rag.cliente_llm import MODELO_LLM

    juez = LangchainLLMWrapper(ChatGroq(
        model=MODELO_LLM, temperature=0, max_tokens=args.max_tokens,
        timeout=args.timeout, max_retries=0,
    ))
    embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(
        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        encode_kwargs={'normalize_embeddings': True},
    ))
    metricas = {'faithfulness': faithfulness, 'answer_relevancy': answer_relevancy}
    configuracion = RunConfig(timeout=args.timeout, max_retries=args.reintentos, max_workers=1)
    print(f'Evaluando {len(seleccion)} preguntas, una métrica a la vez; CSV parcial: {salida}', flush=True)
    detenida = False
    for r in seleccion:
        if detenida:
            break
        for nombre in METRICAS:
            if numero(filas[r['id']].get(nombre)) is not None:
                print(f"{r['id']} {nombre}: ya calculada; se omite", flush=True)
                continue
            dataset = Dataset.from_list([{
                'user_input': r['user_input'],
                'response': r['response'],
                'retrieved_contexts': r['retrieved_contexts'],
            }])
            for intento in range(args.reintentos_429 + 1):
                print(f"{r['id']} {nombre}: evaluando... (intento {intento + 1})", flush=True)
                try:
                    resultado = evaluate(
                        dataset, metrics=[metricas[nombre]], llm=juez,
                        embeddings=embeddings, run_config=configuracion,
                        raise_exceptions=True, show_progress=False,
                    )
                    valor = numero(resultado.to_pandas().iloc[0].get(nombre))
                    filas[r['id']][nombre] = valor
                    print(f"{r['id']} {nombre}: {valor if valor is not None else 'NaN'}", flush=True)
                    break
                except Exception as exc:
                    mensaje = str(exc)
                    print(f"{r['id']} {nombre}: ERROR {type(exc).__name__}: {mensaje}", flush=True)
                    filas[r['id']][nombre] = None
                    es_429 = any(t in mensaje.lower() for t in ('rate limit', 'rate_limit', '429'))
                    if not es_429:
                        print('Error no relacionado con cuota: se continúa con la siguiente métrica.', flush=True)
                        break
                    # Evitar esperar horas ante un límite diario (TPD) o sin información fiable.
                    if 'TPD' in mensaje.upper() or 'tokens per day' in mensaje.lower():
                        print('Límite diario detectado: se detiene conservando el progreso.', flush=True)
                        detenida = True
                        break
                    if intento >= args.reintentos_429:
                        print('Se agotaron los reintentos automáticos de esta métrica.', flush=True)
                        detenida = True
                        break
                    coincidencia = re.search(r'please try again in\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|s|m|h)?', mensaje, re.IGNORECASE)
                    if coincidencia:
                        cantidad = float(coincidencia.group(1))
                        unidad = (coincidencia.group(2) or 's').lower()
                        espera = cantidad * {'ms': 0.001, 's': 1, 'm': 60, 'h': 3600}[unidad]
                    else:
                        espera = 60.0
                    # Margen para ventanas móviles y tokens gastados en subllamadas de RAGAS.
                    espera = max(espera + 15, args.pausa, 60.0)
                    print(f'Esperando {espera:.1f} s antes de reintentar {r["id"]} {nombre}...', flush=True)
                    time.sleep(espera)
                finally:
                    guardar(salida, [filas[r2['id']] for r2 in seleccion])
            if detenida:
                break
            if args.pausa:
                time.sleep(args.pausa)

    for nombre in METRICAS:
        valores = [numero(filas[r['id']].get(nombre)) for r in seleccion]
        validos = [v for v in valores if v is not None]
        print(f'{nombre}: {sum(validos)/len(validos):.6f} ({len(validos)}/{len(seleccion)} válidos)' if validos
              else f'{nombre}: sin resultados válidos (0/{len(seleccion)})')
    print('Guardado:', salida)
    if detenida:
        print('Evaluación pausada por límite de Groq. Puedes ejecutar el mismo comando para reanudar.')


if __name__ == '__main__':
    main()
