# Instructivo de ejecución del proyecto

Este instructivo explica cómo ejecutar el proyecto de forma local y cómo publicarlo temporalmente mediante Cloudflare Tunnel.

---

# Parte A. Ejecución local

## 1. Requisitos previos

Antes de iniciar, se recomienda tener instalado:

- Python 3.13
- Docker Desktop
- Git
- PowerShell
- `cloudflared`

También se debe tener acceso a:

- La base de datos en Neon PostgreSQL
- El repositorio del proyecto
- El archivo `pass.env` con las variables necesarias

La estructura principal del proyecto debe verse aproximadamente así:

```text
proyecto_triaje/
│
├── main.py
├── pass.env
├── requirements.txt
├── docker-compose.yml
├── squema_bd.sql
├── creacion_tablas.ipynb
├── create_roles.ipynb
├── generacion_datos.ipynb
└── ...
```

---

## 2. Descargar el proyecto

Clonar el repositorio:

```powershell
git clone https://github.com/nataliap2005/proyecto-triage.git
```

Entrar a la carpeta del proyecto:

```powershell
cd proyecto-triage
```

---

## 3. Crear el entorno virtual

Crear el entorno virtual:

```powershell
python -m venv .venv
```

Activarlo:

```powershell
.\.venv\Scripts\Activate.ps1
```

Si se activó correctamente, la terminal debe mostrar algo parecido a:

```text
(.venv) PS C:\...\proyecto-triage>
```

---

## 4. Instalar dependencias

Instalar las dependencias desde `requirements.txt`:

```powershell
pip install -r requirements.txt
```

Las principales dependencias utilizadas por el proyecto son:

```text
fastapi
uvicorn
psycopg2-binary
python-dotenv
PyJWT
pwdlib
pydantic
requests
```

---

## 5. Configurar `pass.env`

Cada integrante debe crear localmente un archivo llamado:

```text
pass.env
```

Este archivo **no debe subirse a GitHub**.

Debe contener:

```env
PG_CONNECTION_STRING=CONEXION_DE_NEON
JWT_SECRET_KEY=CLAVE_SECRETA_JWT
HAPI_FHIR_URL=http://localhost:8080/fhir
```

Descripción de las variables:

```text
PG_CONNECTION_STRING → conexión a Neon PostgreSQL
JWT_SECRET_KEY       → clave utilizada para firmar los tokens JWT
HAPI_FHIR_URL        → dirección local del servidor HAPI FHIR
```

No se deben compartir públicamente estos valores.

---

## 6. Base de datos

La base de datos principal está alojada en **Neon PostgreSQL**, por lo que normalmente no es necesario levantar PostgreSQL de forma local.

Para comprobar posteriormente la conexión se puede utilizar:

```text
GET /estado-bd
```

Si fuera necesario crear la base de datos nuevamente desde cero, ejecutar los archivos en este orden:

```text
1. creacion_tablas.ipynb
2. create_roles.ipynb
3. generacion_datos.ipynb
4. inspeccionar_bd.py
```

Si la base de datos ya está creada y poblada en Neon, **no es necesario volver a ejecutar estos archivos**.

---

## 7. Levantar HAPI FHIR

Primero verificar que **Docker Desktop** esté abierto.

Desde la carpeta donde se encuentra `docker-compose.yml`:

```powershell
docker compose up -d
```

Comprobar los contenedores:

```powershell
docker ps
```

Deben aparecer los contenedores correspondientes a HAPI FHIR y su PostgreSQL.

HAPI FHIR debe quedar disponible en:

```text
http://localhost:8080/fhir
```

Para comprobarlo se puede abrir:

```text
http://localhost:8080/fhir/metadata
```

---

## 8. Levantar FastAPI

Con el entorno virtual activo:

```powershell
uvicorn main:app --reload
```

La API quedará disponible en:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

---

## 9. Comprobar el funcionamiento local

En Swagger probar primero:

```text
GET /estado-bd
```

Debe responder aproximadamente:

```json
{
  "estado": "ok"
}
```

Después iniciar sesión mediante:

```text
POST /auth/login
```

Ejemplo:

```json
{
  "username": "USUARIO",
  "password": "CONTRASEÑA"
}
```

Copiar el valor de:

```text
access_token
```

Luego hacer clic en:

```text
Authorize
```

y pegar únicamente el token.

Después comprobar la sesión con:

```text
GET /auth/me
```

---

## 10. Comprobar HAPI FHIR

Con un usuario Admin o Médico:

```text
GET /fhir/estado
```

Debe responder aproximadamente:

```json
{
  "estado": "ok",
  "url": "http://localhost:8080/fhir",
  "fhirVersion": "4.0.1",
  "software": "HAPI FHIR Server"
}
```

Para sincronizar toda la información de la base de datos con HAPI FHIR:

```text
POST /fhir/sincronizar-todo
```

La respuesta esperada es similar a:

```json
{
  "mensaje": "Sincronización FHIR R4 completada",
  "recursos": {
    "Practitioner": 4,
    "Patient": 25,
    "Medication": 12,
    "Encounter": 53,
    "Observation": 318
  }
}
```

Los valores pueden cambiar si la base de datos es modificada.

---

# Parte B. Publicación con Cloudflare Tunnel

Cloudflare Tunnel permite exponer temporalmente los servicios locales por Internet.

Se publican:

```text
FastAPI   → puerto 8000
HAPI FHIR → puerto 8080
```

Durante la demostración deben mantenerse activos:

- Docker Desktop
- HAPI FHIR
- FastAPI
- Tunnel de FastAPI
- Tunnel de HAPI FHIR

---

## 11. Instalar `cloudflared`

Descargar para Windows:

```text
cloudflared-windows-amd64.exe
```

Por ejemplo, guardarlo en:

```text
C:\Users\USUARIO\Downloads
```

Abrir PowerShell y entrar a esa carpeta:

```powershell
cd C:\Users\USUARIO\Downloads
```

Comprobar la instalación:

```powershell
.\cloudflared-windows-amd64.exe --version
```

---

## 12. Publicar FastAPI

Primero dejar FastAPI funcionando:

```powershell
uvicorn main:app --reload
```

Abrir otra ventana de PowerShell:

```powershell
cd C:\Users\USUARIO\Downloads
```

Ejecutar:

```powershell
.\cloudflared-windows-amd64.exe tunnel --url http://localhost:8000
```

Cloudflare mostrará una URL parecida a:

```text
https://xxxxx.trycloudflare.com
```

Esta será la URL pública de FastAPI.

Swagger público:

```text
https://xxxxx.trycloudflare.com/docs
```

No cerrar la ventana del tunnel.

---

## 13. Publicar HAPI FHIR

Abrir otra ventana de PowerShell:

```powershell
cd C:\Users\USUARIO\Downloads
```

Ejecutar:

```powershell
.\cloudflared-windows-amd64.exe tunnel --url http://localhost:8080
```

Cloudflare generará otra URL:

```text
https://yyyyy.trycloudflare.com
```

HAPI FHIR quedará accesible en:

```text
https://yyyyy.trycloudflare.com/fhir
```

La metadata estará disponible en:

```text
https://yyyyy.trycloudflare.com/fhir/metadata
```

---

## 14. Actualizar la URL de HAPI en FastAPI

Modificar el archivo `pass.env`.

Antes:

```env
HAPI_FHIR_URL=http://localhost:8080/fhir
```

Después:

```env
HAPI_FHIR_URL=https://yyyyy.trycloudflare.com/fhir
```

Guardar el archivo.

Reiniciar FastAPI:

```powershell
Ctrl + C
```

Luego:

```powershell
uvicorn main:app --reload
```

---

## 15. Probar el sistema publicado

Desde otro computador o celular abrir:

```text
https://URL_FASTAPI.trycloudflare.com/docs
```

Probar al menos:

```text
GET /estado-bd
POST /auth/login
GET /auth/me
GET /fhir/estado
GET /pacientes/{documento}/historia-clinica
POST /fhir/sincronizar-todo
```

En:

```text
GET /fhir/estado
```

la URL ya no debería aparecer como:

```text
http://localhost:8080/fhir
```

sino como:

```text
https://URL_HAPI.trycloudflare.com/fhir
```

Esto confirma que FastAPI está utilizando el servidor FHIR publicado.

---

# Arquitectura final

```text
                    INTERNET
                       │
              Cloudflare Tunnel
                       │
        ┌──────────────┴──────────────┐
        ↓                             ↓
FastAPI público                 HAPI FHIR público
        │                             │
        │                         FHIR R4
        │
        ↓
Neon PostgreSQL
```

---

# Ventanas que deben permanecer abiertas durante la demostración

No cerrar:

```text
1. Docker Desktop
2. HAPI FHIR mediante Docker Compose
3. FastAPI con Uvicorn
4. Cloudflare Tunnel de FastAPI
5. Cloudflare Tunnel de HAPI FHIR
```

Los Quick Tunnels de Cloudflare generan URLs temporales.

Si se cierra un tunnel y se vuelve a ejecutar, probablemente se generará una URL diferente.

Si cambia la URL pública de HAPI FHIR, también se debe actualizar:

```env
HAPI_FHIR_URL=
```

en `pass.env` y reiniciar FastAPI.

---

# Resumen rápido

## Ejecución local

```text
1. Clonar el repositorio
2. Crear y activar .venv
3. Instalar requirements.txt
4. Crear pass.env
5. Abrir Docker Desktop
6. docker compose up -d
7. uvicorn main:app --reload
8. Abrir http://127.0.0.1:8000/docs
9. Probar /estado-bd
10. Probar /fhir/estado
```

## Publicación con Cloudflare

```text
1. Crear tunnel para HAPI FHIR en puerto 8080
2. Copiar la URL pública de HAPI
3. Actualizar HAPI_FHIR_URL en pass.env
4. Reiniciar FastAPI
5. Crear tunnel para FastAPI en puerto 8000
6. Abrir la URL pública de FastAPI + /docs
7. Probar login, base de datos, historia clínica y FHIR
```

---

# Seguridad

No subir al repositorio:

```text
pass.env
.env
.venv/
__pycache__/
*.pyc
```

Se recomienda incluir estos archivos y carpetas en `.gitignore`.
