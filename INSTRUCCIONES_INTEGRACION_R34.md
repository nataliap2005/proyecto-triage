# Instrucciones de integración R34

## Contenido del ZIP

Son **solo documentos Markdown** para copiar al proyecto; no contiene contraseñas, variables de entorno, pacientes reales ni código nuevo. El ZIP conserva el README completo y los documentos existentes, ampliados con R34.

## Instalación

1. Hacer copia de `README.md` y de `docs/` actuales (o confirmar estado con `git status`).
2. Copiar `README.md` y los archivos de `docs/` de este ZIP a la raíz del repositorio (`proyecto_triaje/`), conservando la estructura de carpetas.
3. Si hubo cambios de compañeras en la misma rama desde el ZIP suministrado, **comparar y fusionar** antes de reemplazar sus secciones; no pisar trabajo reciente.
4. Abrir README y los tres diagramas Mermaid en el preview de Markdown de VS Code (Ctrl+Shift+V).
5. Completar las secciones `...` solo cuando se reciban resultados verificables de Annie y Sarah.
6. Ejecutar pruebas finales y completar `tester.yaml.url_publica` y la URL del repositorio; las contraseñas de demo deben revisarse antes de publicar.

## Archivos

- `README.md`: arquitectura, diagramas de servicios/eventos/intercambio, despliegue y sustenta­ción.
- `docs/STRIDE.md`: matriz original más evidencia R30 y pendientes interinstitucionales.
- `docs/EVENTOS.md`: evento de confirmación de envío y diagrama.
- `docs/DATASETS.md`: **se preserva `## Corpus`** y se añade evidencia R12/R30.
- `docs/LEYES.md`: mapa ampliado R23–R33, con responsabilidades.
- `docs/R30_FHIR.md`: piloto y pendientes explícitos.
- `docs/RAG.md`: copia conservada del documento existente.
- `docs/R34_NATALIA.md`: memoria técnica completa de aportes personales, endpoints, resultados y pruebas.
- `docs/R34_OPERACION.md`: disponibilidad durante toda la jornada, repo, pruebas y sustentación cruzada.
- `docs/R34_PENDIENTES_EQUIPO.md`: tablas y `...` para entregar a Sarah/Annie.

## No cambia

No se modifica `docker-compose.yml`, `tester.yaml`, `back/`, `front/`, `ml/` ni `rag/`. Para probar los cambios Markdown **no** es necesario reconstruir Docker.

## Precauciones

El `tester.yaml` del proyecto adjunto contiene cuentas de demostración con contraseñas escritas en claro y su `url_publica` está vacía. Coordinar con docente el requisito de credenciales demo y **no** publicar secretos reales ni reutilizados. Quick Tunnel no ofrece disponibilidad garantizada por sí solo; mantener host y red activos toda la jornada.
