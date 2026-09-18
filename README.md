# Ejecución del proyecto

> **Importante:** para ejecutar el sistema no es necesario correr los notebooks del backend.  
> La base de datos ya se encuentra creada y alojada en Neon PostgreSQL.
>
> Los notebooks incluidos en el proyecto corresponden a procesos de creación, carga y validación de la base de datos y no hacen parte del proceso normal de ejecución.

---

# Ejecución local

## 1. Clonar el repositorio

```powershell
git clone https://github.com/nataliap2005/proyecto-triage.git
cd proyecto-triage
```

## 2. Entrar al backend

```powershell
cd back
```

## 3. Crear el entorno virtual

```powershell
python -m venv .venv
```

## 4. Activar el entorno virtual

```powershell
.\.venv\Scripts\Activate.ps1
```

## 5. Instalar las dependencias

```powershell
pip install -r requirements.txt
```

## 6. Crear el archivo `pass.env`

Dentro de la carpeta `back/` crear el archivo:

```text
pass.env
```

con las variables necesarias:

```env
PG_CONNECTION_STRING=CONEXION_NEON
JWT_SECRET_KEY=CLAVE_JWT
HAPI_FHIR_URL=http://localhost:8080/fhir
```

> `pass.env` contiene información sensible y no debe subirse al repositorio.

---

## 7. Abrir Docker Desktop

Antes de iniciar HAPI FHIR, verificar que Docker Desktop esté ejecutándose.

---

## 8. Levantar HAPI FHIR

Desde la carpeta donde se encuentra el `docker-compose.yml` de HAPI FHIR:

```powershell
cd HAPI-FHIR
docker compose up -d
```

Verificar los contenedores:

```powershell
docker ps
```

HAPI FHIR debe quedar disponible en:

```text
http://localhost:8080/fhir
```

Se puede comprobar desde:

```text
http://localhost:8080/fhir/metadata
```

---

## 9. Levantar FastAPI

Volver a la carpeta `back/`:

```powershell
cd ..
```

Con el entorno virtual activo:

```powershell
uvicorn main:app --reload
```

FastAPI quedará disponible en:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

---

## 10. Comprobar la base de datos

Desde Swagger probar:

```text
GET /estado-bd
```

La respuesta debe indicar:

```json
{
  "estado": "ok"
}
```

---

## 11. Comprobar HAPI FHIR

Iniciar sesión con un usuario autorizado y probar:

```text
GET /fhir/estado
```

Debe indicar que HAPI FHIR se encuentra disponible.

---

# Ejecutar el frontend

Abrir una nueva terminal.

Desde la raíz del proyecto entrar a:

```powershell
cd front
```

Levantar un servidor web local:

```powershell
python -m http.server 5500
```

Abrir en el navegador:

```text
http://localhost:5500
```

El frontend se conecta con FastAPI y utiliza:

```text
POST /auth/login
GET /auth/me
```

para autenticar al usuario mediante JWT y reconocer su rol.

Actualmente se contemplan los roles:

```text
Admin
Medico
Administrativo
Paciente
```

El frontend está configurado para intentar utilizar primero la API publicada mediante Cloudflare.

Si la URL pública no está disponible, utiliza automáticamente:

```text
http://127.0.0.1:8000
```

Por lo tanto, **Cloudflare no es necesario para trabajar de forma local**.

---

# Publicación con Cloudflare

Cloudflare Tunnel se utiliza cuando se necesita acceder al sistema desde Internet, por ejemplo durante la demostración del proyecto.

Se deben publicar dos servicios:

```text
HAPI FHIR → puerto 8080
FastAPI   → puerto 8000
```

## 1. Publicar HAPI FHIR

Con HAPI FHIR funcionando en:

```text
http://localhost:8080
```

abrir otra terminal y ejecutar:

```powershell
.\cloudflared-windows-amd64.exe tunnel --url http://localhost:8080
```

Cloudflare generará una URL temporal similar a:

```text
https://xxxxx.trycloudflare.com
```

La URL pública de HAPI FHIR será:

```text
https://xxxxx.trycloudflare.com/fhir
```

---

## 2. Actualizar `HAPI_FHIR_URL`

Modificar en:

```text
back/pass.env
```

la variable:

```env
HAPI_FHIR_URL=https://xxxxx.trycloudflare.com/fhir
```

---

## 3. Reiniciar FastAPI

Detener Uvicorn con:

```text
Ctrl + C
```

y volver a ejecutarlo:

```powershell
uvicorn main:app --reload
```

Esto permite que FastAPI utilice la nueva URL pública de HAPI FHIR.

---

## 4. Publicar FastAPI

Abrir otra terminal y ejecutar:

```powershell
.\cloudflared-windows-amd64.exe tunnel --url http://localhost:8000
```

Cloudflare generará otra URL:

```text
https://yyyyy.trycloudflare.com
```

Swagger quedará disponible públicamente en:

```text
https://yyyyy.trycloudflare.com/docs
```

---

## 5. Probar los servicios públicos

Probar:

```text
POST /auth/login
GET /auth/me
GET /estado-bd
GET /fhir/estado
GET /pacientes/{documento}/historia-clinica
POST /fhir/sincronizar-todo
```

---

# Resumen de ejecución

## Local

### Terminal 1 - Backend

```powershell
cd back
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload
```

### Terminal 2 - HAPI FHIR

```powershell
cd back\HAPI-FHIR
docker compose up -d
```

### Terminal 3 - Frontend

```powershell
cd front
python -m http.server 5500
```

Abrir:

```text
Frontend:
http://localhost:5500

Swagger:
http://127.0.0.1:8000/docs

HAPI FHIR:
http://localhost:8080/fhir
```

---

## Con Cloudflare

Mantener activos:

```text
1. Docker Desktop
2. HAPI FHIR
3. FastAPI
4. Frontend
5. Tunnel de HAPI FHIR
6. Tunnel de FastAPI
```

Si Cloudflare no está disponible, el proyecto puede seguir ejecutándose completamente de forma local.

---

# Notas

- No ejecutar los notebooks para iniciar el proyecto.
- No volver a crear la base de datos si ya se está utilizando la instancia de Neon.
- No subir `pass.env` al repositorio.
- Las URLs `trycloudflare.com` son temporales y pueden cambiar cada vez que se reinicia el tunnel.
- Si cambia la URL pública de HAPI FHIR, actualizar `HAPI_FHIR_URL` en `pass.env` y reiniciar FastAPI.
- Para desarrollo local, Cloudflare es opcional.
