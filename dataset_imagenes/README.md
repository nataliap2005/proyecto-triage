# Dataset de imágenes (R06)

## 1. Resumen

Las radiografías del sistema provienen de cuatro datasets públicos y reales (no sintéticos): FracAtlas, NIH ChestX-ray14 y BUU-LSPINE. Se cargaron 10 imágenes en el PACS (Orthanc), una por cada paciente sintético de la demostración. Cada imagen queda vinculada al encuentro y al examen de imagenología que solicitó el médico, y se visualiza desde la ficha del paciente.

- Número de imágenes cargadas en Orthanc: 10
- Tipo de estudio: radiografía convencional (tórax, extremidades y columna)

## 2. Datasets utilizados

| Dataset          | Fuente                                                                                                                                                                                                                                                                                                                                                                                  | Licencia o términos                                                                                                                                                                                                        | Región anatómica              | Imágenes cargadas |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- | ----------------- |
| FracAtlas        | Abedeen, I., Rahman, M. A., Zohra Prottyasha, F., Ahmed, T., Mohmud Chowdhury, T., & Shatabda, S. (2026). FracAtlas: A Dataset for Fracture Classification, Localization and Segmentation of Musculoskeletal Radiographs (Versión 7) [Conjunto de datos]. Figshare. https://doi.org/10.6084/m9.figshare.22363012.v7                                                                     | CC BY 4.0, permite copiar, compartir y redistribuir el material. Transformarlo o construir sobre los datos para cualquier propósito, siempre que se haga una mención obligatoria de la licencia.                           | Mano, hombro, pierna y cadera | 6                 |
| NIH ChestX-ray14 | Wang, X., Peng, Y., Lu, L., Lu, Z., Bagheri, M., & Summers, R. (2017). ChestX-ray8: Hospital-scale chest X-ray database and benchmarks on weakly-supervised classification and localization of common thorax diseases. Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (CVPR), 3462–3471. Sitio de descarga: https://nihcc.app.box.com/v/ChestXray-NIHCC. | Uso público irrestricto (NIH Clinical Center). Sin licencia formal tradicional. Libre para fines comerciales y académicos bajo atribución obligatoria al artículo original y al instituto proveedor                        | Tórax                         | 3                 |
| BUU-LSPINE       | Faculty of Informatics, Burapha University. (s.f.). Burapha Spine Dataset (Versión 0.1) [Conjunto de datos de imágenes de rayos X]. https://services.informatics.buu.ac.th/spine                                                                                                                                                                                                        | Acuerdo de licencia de usuario final de la Universidad de Burapha: no intentar identificar a los participantes, reconocer al Burapha Spine Dataset al presentar resultados y no usar el nombre de la universidad como aval | Columna lumbar                | 1                 |
| **Total**        |                                                                                                                                                                                                                                                                                                                                                                                         |                                                                                                                                                                                                                            |                               | **10**            |

Tamaño de cada dataset completo:

- FracAtlas: 4.083 radiografías de mano, pierna, cadera y hombro, de las cuales 717 tienen fractura. Fueron anotadas por dos radiólogos y un ortopedista.
- NIH ChestX-ray14: 112.120 radiografías frontales de tórax de 30.805 pacientes, con 14 hallazgos etiquetados.
- BUU-LSPINE: radiografías lumbares en vista anteroposterior y lateral, con anotaciones de cuatro tipos de listesis. Versión descargada: muestra BUU-LSPINE(400)\_sample de la versión 0.1 del Burapha Spine Dataset, con 400 pares de imágenes (vista AP y lateral) de 400 pacientes distintos, diagnosticados por médicos.

## 3. Justificación de la relación con el problema clínico

El sistema apoya el triage en urgencias. Los casos de la demostración son motivos de consulta frecuentes en los que el médico solicita una radiografía: traumatismos musculoesqueléticos (muñeca, mano, tobillo, hombro, rodilla, cadera y columna lumbar) y cuadros torácicos o respiratorios (trauma de tórax, neumonía, tos con disnea). Los datasets se eligieron porque cubren esas regiones con imágenes reales.

Se usan varios datasets porque ninguno de los revisados cubre todas las regiones anatómicas de los casos:

- FracAtlas es un dataset de fracturas con anotaciones de especialistas, pertinente para los traumatismos de mano, hombro, rodilla, tobillo y cadera.
- NIH ChestX-ray14 incluye hallazgos como neumonía, neumotórax, derrame y enfisema, propios de la consulta de urgencias por síntomas respiratorios y trauma de tórax.
- BUU-LSPINE aporta radiografías lumbares en dos vistas y se usa como ejemplo de estudio de columna lumbar.

## 4. Preparación de las imágenes

Los datasets públicos entregan las imágenes en JPG o PNG, no en DICOM, que es el formato que maneja el PACS. Por eso cada imagen se convirtió a DICOM con un script en Python (librerías PIL y pydicom):

- La imagen se pasa a escala de grises de 8 bits.
- Se generan identificadores únicos DICOM (UID) propios para el estudio, la serie y la imagen de cada radiografía, para que el PACS pueda organizarlas.
- Se asignan identificadores sintéticos de paciente (PatientName ANONYMOUS y PatientID DEMO001, DEMO002, etc.) y se marca el archivo como desidentificado. No se importaron metadatos del archivo de origen.
- Se guardan como imágenes de captura secundaria (Secondary Capture), con modalidad DX (radiografía digital).

Después, un usuario con rol Médico carga cada archivo desde el frontend (sección Imágenes PACS), eligiendo el paciente, el encuentro y el examen correspondientes.

## 5. Trazabilidad por paciente

| #   | Paciente sintético (documento) | Examen solicitado                | Dataset de origen  |
| --- | ------------------------------ | -------------------------------- | ------------------ |
| 1   | Paciente 1 (1200001001)        | Radiografía de muñeca derecha    | FracAtlas (mano)   |
| 2   | Paciente 2 (1200001002)        | Radiografía de tobillo izquierdo | FracAtlas (pierna) |
| 3   | Paciente 3 (1200001003)        | Radiografía de tórax             | NIH ChestX-ray14   |
| 4   | Paciente 4 (1200001004)        | Radiografía de hombro derecho    | FracAtlas (hombro) |
| 5   | Paciente 5 (1200001005)        | Radiografía de rodilla izquierda | FracAtlas (pierna) |
| 6   | Paciente 6 (1200001006)        | Radiografía de pelvis y cadera   | FracAtlas (cadera) |
| 7   | Paciente 7 (1200001007)        | Radiografía de mano derecha      | FracAtlas (mano)   |
| 8   | Paciente 8 (1200001008)        | Radiografía de tórax             | NIH ChestX-ray14   |
| 9   | Paciente 9 (1200001009)        | Radiografía de tórax             | NIH ChestX-ray14   |
| 10  | Paciente 10 (1200001010)       | Radiografía de columna lumbar    | BUU-LSPINE         |

## 6. Limitaciones

1. **Asignación demostrativa.** Cada imagen pertenece a una persona real del dataset de origen, no al paciente sintético al que se asocia en el sistema. No hay relación clínica real entre ambos.
2. **Calidad de las imágenes.** Las imágenes de origen son JPG o PNG, ya comprimidas o redimensionadas por sus autores, y se convirtieron a DICOM de 8 bits. No conservan los metadatos originales (como el espaciado de píxel) y no son aptas para uso diagnóstico.
3. **Etiquetas de NIH ChestX-ray14.** Se extrajeron automáticamente de los informes radiológicos, con una precisión esperada superior al 90 % según sus autores, y no por lectura de un radiólogo imagen por imagen.
4. **Pertinencia parcial.** BUU-LSPINE está orientado a la listesis lumbar y no al trauma agudo. Además, alguna imagen asignada puede no mostrar el hallazgo descrito en el caso clínico sintético.
5. **Población.** FracAtlas proviene de hospitales de Bangladesh, NIH ChestX-ray14 de centros de Estados Unidos, y BUU-LSPINE de Tailandia. No representan a la población colombiana.

## 7. Referencias

- Abedeen, I., Rahman, M. A., Zohra Prottyasha, F., Ahmed, T., Mohmud Chowdhury, T., & Shatabda, S. (2026). FracAtlas: A Dataset for Fracture Classification, Localization and Segmentation of Musculoskeletal Radiographs (Versión 7) [Conjunto de datos]. Figshare. https://doi.org/10.6084/m9.figshare.22363012.v7
- Wang, X., Peng, Y., Lu, L., Lu, Z., Bagheri, M., & Summers, R. (2017). ChestX-ray8: Hospital-scale chest X-ray database and benchmarks on weakly-supervised classification and localization of common thorax diseases. Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (CVPR), 3462–3471. Sitio de descarga: https://nihcc.app.box.com/v/ChestXray-NIHCC.
- Faculty of Informatics, Burapha University. (s.f.). Burapha Spine Dataset (Versión 0.1) [Conjunto de datos de imágenes de rayos X]. https://services.informatics.buu.ac.th/spine
