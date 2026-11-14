# Datasets del proyecto

Este documento describe los dos conjuntos de datos del sistema: el **tabular** (triaje, modelo de IA y clusters) y el de **imágenes** (PACS). Cada cifra proviene de los archivos del repositorio (`dataset_v1/`, `back/preprocesamiento/salida_ia/`);y el corpus documental del agente clínico RAG.

---

## Tabular

### 1.1 Fuentes

| Fuente | Qué es | Registros usados | Enlace y condiciones |
|---|---|---|---|
| **KTAS** (Corea del Sur) | Revisión de historias clínicas de urgencias de dos hospitales académicos urbanos (uno regional y uno local), 20 días elegidos al azar entre octubre de 2016 y septiembre de 2017. De 1.540 registros recogidos, 1.267 entraron en el análisis publicado. | 1.267 (`dataset_v1/data.csv`) | Moon S-H, Shim JL, Park K-S, Park C-S. *Triage accuracy and causes of mistriage using the Korean Triage and Acuity Scale.* PLOS ONE 2019;14(9):e0216972. DOI [10.1371/journal.pone.0216972](https://doi.org/10.1371/journal.pone.0216972). Licencia **CC BY 4.0** (atribución). Los datos están en el material de apoyo del artículo (S1 Appendix). |
| **NHAMCS 2022, urgencias** (EE. UU.) | *National Hospital Ambulatory Medical Care Survey*, módulo de servicios de urgencias. Encuesta por muestreo del NCHS/CDC. | 12.999 visitas de edad ≥ 16 (`dataset_v1/ed2022-spss.sav`) | Archivo `ed2022.zip` y documentación `doc22-ed-508.pdf` en [cdc.gov/nchs/nhamcs/documentation](https://cdc.gov/nchs/nhamcs/documentation/index.html). Archivo de uso público, con condiciones de uso (ver 1.9). |

> **Nota sobre KTAS.** El archivo `data.csv` del repositorio tiene 1.267 filas, el mismo número de registros analizados en el artículo (de 1.540 recogidos).

### 1.2 Homologación

Los dos orígenes usan escalas y variables distintas. Se unificaron en un solo esquema (`dataset_v1/triaje_homologado.csv`, 14.266 visitas) con `dataset_v1/homologar_triaje.py`. El detalle variable por variable está en `homologacion_variables.xlsx` y el diccionario del `.sav` en `diccionario_ED2022.xlsx`.

Supuesto principal: **los niveles de la escala ESI/NHAMCS y de KTAS se tratan como equivalentes** (1 = reanimación … 5 = no urgente). Es razonable porque ambas son escalas de cinco niveles, pero **es un supuesto, no una validación**. El `source` (`fuente`) de cada fila se conserva para poder medir sesgo por origen.

### 1.3 Variable objetivo (etiqueta)

La etiqueta es el **nivel de triaje asignado por enfermería** (KTAS: `KTAS_RN`; NHAMCS: `IMMEDR`). Se agrupa en tres categorías:

| Categoría | Niveles |
|---|---|
| Crítico | 1 y 2 |
| Medio | 3 |
| No crítico | 4 y 5 |

**Consecuencia importante:** el modelo aprende a imitar el criterio de la enfermera de triaje, no un desenlace clínico (hospitalización, muerte). Si el triaje de enfermería se equivocó, el modelo hereda ese error. El nivel que asignó el médico experto en KTAS (`triaje_experto`) **no se usó para entrenar**; solo sirve para la comparación de la sección 3 de `MODELO.md`.

### 1.4 Variables

El modelo recibe 12 variables (las mismas que usa la API al llamar a `/predecir`):

| Variable | Tipo | Notas |
|---|---|---|
| `edad` | numérica | Se calcula desde la fecha de nacimiento. Se rechaza < 18 o > 120. |
| `sexo_M` | binaria | Si el sexo no está registrado, se trata como femenino y se devuelve un aviso. |
| `llegada_ambulancia` | binaria | |
| `lesion` | binaria | Indica si el motivo es una lesión. |
| `fc`, `fr` | numérica | Frecuencia cardiaca y respiratoria. |
| `pas`, `pad` | numérica | Presión arterial sistólica y diastólica. |
| `temp_c` | numérica | Temperatura en °C. |
| `spo2` | numérica | Saturación de oxígeno (%). |
| `dolor_nrs` | numérica | Dolor 0–10. |
| `motivo_categoria` | categórica (13) | Motivo de consulta agrupado. |

Variables que **no** se usan: `triaje_experto`, `mental_avpu` (solo existe en KTAS), `peso_encuesta` (solo NHAMCS), `motivo_original`, `id_original`, `dolor_si`. No se incluyeron indicadores de dato faltante porque permiten adivinar el país de origen (AUC 0,80 solo con ellos), lo que haría que el modelo aprendiera el hospital y no al paciente.

### 1.5 Filtros y particiones

| Paso | Registros restantes | Quitados |
|---|---|---|
| Base homologada (KTAS + NHAMCS) | 14.266 | — |
| Se excluyen menores de 18 años | 13.852 | 414 |
| Se excluyen visitas sin nivel de triaje | 9.415 | 4.437 |
| Se excluyen visitas con ≥ 3 de 6 signos vitales ausentes | 9.317 | 98 |
| Se eliminan duplicados exactos | **9.304** | 13 |

Los 9.304 registros finales son 1.226 de KTAS y 8.078 de NHAMCS. La partición es estratificada por fuente y nivel:

| Conjunto | Total | KTAS | NHAMCS |
|---|---|---|---|
| Entrenamiento | 7.443 | 980 | 6.463 |
| Prueba | 1.861 | 246 | 1.615 |

Distribución de niveles (1 → 5): KTAS 0,7 / 16,6 / 35,9 / 40,0 / 6,8 %; NHAMCS 1,4 / 17,1 / 55,1 / 23,7 / 2,6 %.

### 1.6 Datos faltantes

Los faltantes se imputan dentro del pipeline del modelo (ajustado solo con entrenamiento). Las proporciones de partida son: `dolor_nrs` 21,6 % y `spo2` 8,3 % del total. Pero no se reparten igual: en KTAS falta la SpO₂ en cerca del 53,5 % de las filas y en NHAMCS falta el dolor en cerca del 25 %.

### 1.7 Clusters (R07)

**Método.** k-means sobre `edad`, `fc`, `fr`, presión arterial media (PAM), `temp_c` y `spo2`, estandarizadas. Se **excluyen** la etiqueta de triaje, el país y el dolor, para que los grupos sean fisiológicos y no repitan lo que el modelo supervisado ya predice. La PAM sustituye a PAS y PAD para no contar dos veces la presión.

**Por qué k = 5.**

| Criterio | Resultado |
|---|---|
| Silueta | ≈ 0,165 en k = 5, máximo local frente a k = 3, 4 y 6. k = 2 puntúa más alto, pero solo separa jóvenes de mayores y no sirve clínicamente. |
| Estabilidad (bootstrap) | ARI ≈ 0,89–0,90: los grupos se reproducen al remuestrear. |
| Davies-Bouldin | No indica un k claro. |
| Relación con el país | V de Cramér ≈ 0,106: los grupos no son un artefacto de la fuente. |
| Otros algoritmos | Jerárquico (ARI 0,45 con k-means), GMM (ARI 0,27, 20 % en zona gris), DBSCAN (un solo grupo denso; el "ruido" son los pacientes más graves, 47 % críticos frente al 17 %). Se mantiene k-means por estabilidad e interpretabilidad. |

La silueta es baja (0,165) porque los signos vitales de los pacientes forman un continuo y no grupos bien separados. Los clusters se presentan como **grupos descriptivos**, no como diagnósticos.

**Interpretación** (`back/preprocesamiento/salida_ia/clusters.json`; los porcentajes son del conjunto real de 9.304):

| Cluster | Reales | Sintéticos | % crítico |
|---|---|---|---|
| Adultos mayores estables | 2.585 | 56 | 20,3 |
| Taquicardia / febril | 1.347 | 29 | 24,4 |
| Compromiso respiratorio | 162 | 10 | 50,6 |
| Hipertensión arterial | 2.028 | 43 | 20,6 |
| Jóvenes con signos estables | 3.182 | 62 | 11,2 |

**Zonas de confusión.** (1) *Jóvenes con signos estables*: contienen críticos con signos normales, que el modelo tiende a subestimar. (2) *Taquicardia / febril*: es una frontera, con cerca de la mitad de sus puntos con silueta negativa. (3) Entre *adultos mayores*, *hipertensión* y *taquicardia* se mezclan los niveles 2 y 3.

### 1.8 Pacientes sintéticos

Son 200 pacientes (`cohorte_sintetica.csv`), generados **solo para demostrar la cohorte en el sistema**; no se usaron para entrenar.

- **Método:** interpolación `nuevo = base + u · (vecino − base)` con `u` aleatorio en [0, 1], entre dos pacientes del **mismo cluster y del mismo nivel de triaje**. Se interpolan las 8 variables numéricas; las categóricas se copian de la base; los faltantes se conservan.
- **Bases:** salen del conjunto de **prueba**, así no contaminan el entrenamiento.
- **Reparto:** proporcional al tamaño del cluster, con mínimo de 10 por grupo.
- **Marca:** `origen = 'sintetico'` en `pacientes` (restricción `CHECK` real/sintetico) y registro en `ia_cohorte` con `id_cluster` y `grupo`. El documento es `SINT-0001`, etc.

Comprobaciones hechas por el equipo de datos: el 99,5 % de los sintéticos se reasigna a su cluster; ninguno es idéntico a un registro real; el AUC del modelo sobre ellos es 0,761 frente a 0,765 en real.

El endpoint `GET /ia/clusters` devuelve `[{cluster, nombre, descripcion, n_reales, n_sinteticos, pct_critico, mediana}]`.

### 1.9 Condiciones de uso y privacidad

- **KTAS:** CC BY 4.0. Se debe citar el artículo (ver tabla 1.1).
- **NHAMCS:** el NCHS exige usar los datos solo para reporte y análisis estadístico, no intentar identificar a ninguna persona o establecimiento, y no vincularlos con datos identificables de otras fuentes. El proyecto cumple: son datos anónimos y no se cruzan con otras bases. Además, NHAMCS es una **encuesta con diseño muestral**: sus pesos son necesarios para estimar cifras nacionales. Aquí se usa como fuente de ejemplos de entrenamiento, no para estimar poblaciones, y por eso **no se aplican los pesos**.
- Los pacientes reales de la aplicación son ficticios; ningún dato de las fuentes públicas se asocia a una persona del hospital.

### 1.10 Limitaciones

1. Solo adultos (≥ 18). El sistema rechaza menores.
2. Las filas de NHAMCS sin nivel de triaje (4.437) se eliminaron; si faltaban al azar no hay sesgo, pero no hay forma de comprobarlo.
3. La equivalencia entre ESI y KTAS es un supuesto.
4. NHAMCS no trae nivel de conciencia (AVPU) y KTAS sí; por eso esa variable no entra al modelo.
5. Son datos de Corea y EE. UU.: no se han validado con pacientes del Hospital San Andrés de Tumaco, con perfil epidemiológico distinto.
6. La etiqueta es el triaje de enfermería (ver 1.3).

---

## Imagen

Las radiografías del sistema provienen de **tres datasets públicos y reales** (no sintéticos): FracAtlas, NIH ChestX-ray14 y BUU-LSPINE. Se cargaron **10 imágenes** en el PACS (Orthanc), una por cada paciente de la demostración. Cada imagen queda vinculada al encuentro y al examen de imagenología que solicitó el médico, y se visualiza desde la ficha del paciente. El detalle completo y los archivos DICOM están en la carpeta [`dataset_imagenes/`](../dataset_imagenes/).

### 2.1 Datasets utilizados

| Dataset | Fuente | Licencia o términos | Región | Imágenes cargadas |
|---|---|---|---|---|
| FracAtlas | Abedeen et al. (2026). *FracAtlas: A Dataset for Fracture Classification, Localization and Segmentation of Musculoskeletal Radiographs* (v7). Figshare. https://doi.org/10.6084/m9.figshare.22363012.v7 | CC BY 4.0 (atribución) | Mano, hombro, pierna y cadera | 6 |
| NIH ChestX-ray14 | Wang et al. (2017). *ChestX-ray8*. CVPR, 3462–3471. Descarga: https://nihcc.app.box.com/v/ChestXray-NIHCC | Uso público del NIH Clinical Center; atribución al artículo y al instituto | Tórax | 3 |
| BUU-LSPINE | Faculty of Informatics, Burapha University. *Burapha Spine Dataset* (v0.1). https://services.informatics.buu.ac.th/spine | Acuerdo de usuario final: no identificar a los participantes, reconocer al dataset y no usar el nombre de la universidad como aval | Columna lumbar | 1 |
| **Total** | | | | **10** |

Tamaño de los datasets completos: FracAtlas, 4.083 radiografías (717 con fractura); NIH ChestX-ray14, 112.120 radiografías frontales de 30.805 pacientes; BUU-LSPINE, muestra de 400 pares de imágenes (vista AP y lateral) de la versión 0.1.

### 2.2 Por qué responden al problema clínico

El sistema apoya el triaje en urgencias. Los casos de la demostración son motivos de consulta frecuentes en los que el médico solicita una radiografía: traumatismos musculoesqueléticos (muñeca, mano, tobillo, hombro, rodilla, cadera y columna lumbar) y cuadros torácicos o respiratorios. Se usan varios datasets porque ninguno cubre todas las regiones: FracAtlas aporta fracturas con anotaciones de especialistas, NIH ChestX-ray14 aporta hallazgos como neumonía, neumotórax y enfisema, y BUU-LSPINE aporta columna lumbar en dos vistas.

### 2.3 Preparación y privacidad

Los datasets entregan JPG o PNG, no DICOM. Cada imagen se convirtió con un script en Python (PIL y pydicom): escala de grises de 8 bits, identificadores únicos DICOM (UID) propios para estudio, serie e imagen, y modalidad DX como *Secondary Capture*. Se asignan identificadores sintéticos (PatientName `ANONYMOUS`, PatientID `DEMO001`, `DEMO002`, etc.) y no se importaron metadatos del archivo de origen. Los archivos están en `dataset_imagenes/`.

### 2.4 Trazabilidad por paciente

| Paciente (documento) | Examen solicitado | Dataset de origen |
|---|---|---|
| 1200001001 | Radiografía de muñeca derecha | FracAtlas (mano) |
| 1200001002 | Radiografía de tobillo izquierdo | FracAtlas (pierna) |
| 1200001003 | Radiografía de tórax | NIH ChestX-ray14 |
| 1200001004 | Radiografía de hombro derecho | FracAtlas (hombro) |
| 1200001005 | Radiografía de rodilla izquierda | FracAtlas (pierna) |
| 1200001006 | Radiografía de pelvis y cadera | FracAtlas (cadera) |
| 1200001007 | Radiografía de mano derecha | FracAtlas (mano) |
| 1200001008 | Radiografía de tórax | NIH ChestX-ray14 |
| 1200001009 | Radiografía de tórax | NIH ChestX-ray14 |
| 1200001010 | Radiografía de columna lumbar | BUU-LSPINE |

### 2.5 Cómo se cargan

`POST /pacs/estudios` recibe `id_paciente`, `id_encuentro`, `id_examen` y el archivo DICOM (el front limita a 20 MB, `.dcm`). El estudio queda en `estudios_imagenes`, enlazado al paciente. `GET /pacientes/{documento}/imagenes` lista los estudios del paciente, y hay endpoints para estudios, instancias y vista previa.

### 2.6 Limitaciones

1. Cada imagen pertenece a una persona real del dataset de origen, no al paciente ficticio al que se asocia en el sistema: la asignación es demostrativa.
2. Las imágenes de origen son JPG o PNG ya comprimidas y se convirtieron a DICOM de 8 bits, sin los metadatos originales (como el espaciado de píxel). No son aptas para uso diagnóstico.
3. Las etiquetas de NIH ChestX-ray14 se extrajeron automáticamente de informes radiológicos, con una precisión esperada superior al 90 % según sus autores.
4. BUU-LSPINE está orientado a la listesis lumbar y no al trauma agudo; alguna imagen puede no mostrar el hallazgo del caso ficticio.
5. Las poblaciones son de Bangladesh, Estados Unidos y Tailandia; no representan a la población colombiana.

---



## Corpus

### 3.1 Fuentes documentales

El agente clínico RAG utiliza un corpus de guías y protocolos clínicos pertinentes a la atención de urgencias y al proceso de triaje, complementado con historias clínicas aprobadas de pacientes sintéticos. Su función es proporcionar información de apoyo al profesional sanitario mediante respuestas fundamentadas en documentos recuperados, sin sustituir la valoración clínica.

Las principales fuentes documentales son:

| Documento | Institución | Aplicación |
|---|---|---|
| Resolución 5596 de 2015 | Ministerio de Salud y Protección Social de Colombia | Categorías, criterios y responsabilidades del triaje. |
| Atención básica de emergencia: abordaje de lesionados y enfermos agudos | OMS, CICR e IFEM | Evaluación inicial y manejo de pacientes en urgencias. |
| Recent-onset chest pain of suspected cardiac origin (CG95) | NICE | Evaluación del dolor torácico. |
| Acutely ill adults in hospital: recognising and responding to deterioration (CG50) | NICE | Reconocimiento del deterioro clínico. |
| Major trauma: assessment and initial management (NG39) | NICE | Evaluación y manejo inicial del trauma grave. |

Los documentos originales y sus textos procesados se encuentran en `rag/documentos/`. Las fuentes y referencias específicas se documentan en `docs/RAG.md`.

### 3.2 Preparación e indexación

El procesamiento documental se realiza mediante los módulos de la carpeta `rag/`:

- **Extracción:** `rag/extraer_pdfs.py` obtiene el texto de los documentos por página, conservando la información necesaria para identificar las fuentes.
- **Fragmentación:** los textos se dividen en fragmentos de hasta 1.100 caracteres, con un solapamiento de 180 caracteres.
- **Embeddings:** se utiliza `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, con vectores de 384 dimensiones generados localmente.
- **Almacenamiento:** los fragmentos y embeddings se almacenan en PostgreSQL (Neon), mediante la extensión pgvector.
- **Recuperación:** se utiliza búsqueda semántica densa (`RAG_METODO=dense`), seleccionada a partir de la evaluación de los métodos BM25, denso e híbrido.

El sistema conserva metadatos de fuente, título, página y fragmento para permitir la trazabilidad de las respuestas.

### 3.3 Historias clínicas y privacidad

El corpus también puede incorporar información de encuentros clínicos aprobados de pacientes sintéticos.

Solamente se indexan encuentros con `aprobado_rag = TRUE`. Antes de indexar se aplica seudonimización mediante HMAC-SHA256, evitando almacenar identificadores personales directos en los fragmentos clínicos.

Las consultas están restringidas según el rol y los permisos del profesional. El agente utiliza únicamente información documental autorizada y puede acceder a historias clínicas aprobadas cuando corresponde.

### 3.4 Validación del sistema RAG

La recuperación documental se evaluó utilizando 20 preguntas con fragmentos relevantes identificados manualmente. El método denso presentó los mejores resultados entre las estrategias evaluadas, con Recall@3 de 0,29 y MRR@20 de 0,48.

En la evaluación parcial de generación mediante RAGAS, sobre ocho preguntas válidas, se registraron valores promedio de:

- Faithfulness: 0,85.
- Answer relevancy: 0,78.

Adicionalmente, durante la validación funcional del proyecto se obtuvieron los siguientes resultados:

- 18 pruebas automatizadas aprobadas.
- Respuestas sobre las cinco categorías de triaje respaldadas por la Resolución 5596 de 2015.
- Identificación correcta de los profesionales autorizados para realizar el triaje.
- Abstención ante preguntas sin evidencia suficiente.
- Consultas funcionales desde el frontend con fuentes citadas.
- Restricciones de acceso verificadas para distintos roles.

Los resultados de RAGAS son parciales y no representan una evaluación completa de las 20 preguntas.

### 3.5 Limitaciones

1. La calidad de las respuestas depende de los fragmentos recuperados y de la información disponible en el corpus.
2. Algunos documentos pueden presentar errores de extracción de texto.
3. Las historias clínicas indexadas corresponden exclusivamente a encuentros sintéticos aprobados.
4. Las evaluaciones disponibles no constituyen una validación clínica del sistema.
5. El agente funciona como apoyo documental y no realiza el triaje formal ni reemplaza el criterio del profesional sanitario.

Para más detalles sobre arquitectura, evaluación, permisos y funcionamiento del agente, consultar [`RAG.md`](RAG.md).



## Fuentes

- Moon S-H, Shim JL, Park K-S, Park C-S. *Triage accuracy and causes of mistriage using the Korean Triage and Acuity Scale.* PLOS ONE 2019;14(9):e0216972. https://doi.org/10.1371/journal.pone.0216972
- Datasets de imágenes: ver tabla de la sección Imagen.
- NCHS/CDC. *NHAMCS 2022 – Emergency Department public use data file* y documentación. https://cdc.gov/nchs/nhamcs/documentation/index.html

## Documentos relacionados

[`MODELO.md`](MODELO.md) · [`LEYES.md`](LEYES.md) · [README](../README.md)


## R34 · Evidencia suplementaria de minimización del corpus y del intercambio

- **Corpus R23:** se indexan guías permitidas e historias **sintéticas previamente aprobadas** con seudonimización y filtros de paciente/encuentro antes de recuperar fragmentos. Una consulta sin soporte devuelve abstención; citar F1/F3/etc. no reemplaza revisar que los fragmentos respalden su contenido.
- **Prueba canario R12:** se informó ejecución sobre 1758 fragmentos y 585 identificadores asociados, filtros clínicos probados con cinco seudónimos, sin fugas detectadas en el ensayo. Esta evidencia no certifica ausencia universal de identificadores.
- **Canal FHIR R30:** **no se vuelca el corpus completo ni todas las historias** al socio. Se construye un Bundle para la remisión concreta con historia relevante autorizada: `Patient` seudonimizado, consentimiento, solicitud, Task, observaciones codificadas e informes finales aprobados. El caso sintético #14 contenía seis signos vitales y un informe aprobado.
- **Regla operativa:** no utilizar pacientes etiquetados `origen='real'` en pruebas de intercambio R30; revocación de consentimiento impide construir/envío según la política implementada. El prototipo no debe utilizarse como circuito clínico productivo.

**Pendiente R33 / Annie:** `...` catálogo de campos mínimos acordados con el receptor externo, terminologías finales y evidencia de filtrado en entrada. **Pendiente Sarah:** `...` evidencia de cifrado de campos sensibles en reposo.
