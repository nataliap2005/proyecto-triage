# Frontend SPA — Sistema de Triaje Hospitalario

Frontend estático en HTML/CSS/JavaScript, servido por Nginx y pensado para el backend modular actual.

## Incluye
- Login JWT y restauración de sesión con `/auth/me`.
- Vistas adaptadas a Admin, Medico, Administrativo y Paciente.
- Indicadores de API, BD, FHIR y PACS.
- Búsqueda de paciente por documento.
- Ficha del paciente e historia clínica unificada.
- Pestaña de imágenes PACS.
- Visor con brillo, contraste, zoom, pan, inversión y reset.
- Administración de usuarios, desbloqueo, restauración y eliminación lógica.
- Logs de autenticación y auditoría.
- Consulta básica de facturación.
- Presentación de fechas en `America/Bogota` sin cambiar el almacenamiento UTC del backend.

## Integración
El JavaScript usa `/api` como base. `nginx.conf` redirige `/api/*` hacia `http://api:8000/*`. Por eso el servicio del backend en `docker-compose.yml` debe llamarse `api`.

Servicio recomendado en `docker-compose.yml`:

```yaml
frontend:
  build: ./front
  container_name: triaje-frontend
  restart: unless-stopped
  ports:
    - "8080:80"
  depends_on:
    - api
```

Luego reconstruya:

```powershell
docker compose up -d --build
```

y abra `http://localhost:8080`.

## Importante
El formulario de creación de usuarios asume los IDs iniciales de roles del esquema: `1 Admin`, `2 Medico`, `3 Administrativo`, `4 Paciente`. Si en la base real los IDs cambiaron, ajuste el `<select>` en `js/admin.js` o cree un endpoint de catálogo de roles.

El preview PACS actualmente está permitido por el backend para Admin y Medico. Aunque el listado de estudios permite Paciente, un paciente no podrá abrir el preview hasta que el backend autorice de forma segura esa lectura verificando propiedad.

La carga DICOM desde interfaz no fue incluida en este paquete: el backend ya la soporta, pero antes de exponerla al usuario conviene definir qué roles pueden cargar, elegir el encuentro/examen correcto y auditar esa acción.

## Carga DICOM desde el frontend

En la pestaña **Imágenes PACS** del rol Médico se muestra un formulario para cargar archivos `.dcm` de hasta 20 MB. El paciente se toma de la ficha abierta; el médico selecciona un encuentro y un examen ya existentes, agrega una descripción opcional y el frontend envía el archivo como `application/dicom` a `POST /pacs/estudios`. Al finalizar, la lista de estudios se refresca automáticamente y el nuevo estudio queda disponible en el visor PACS.
