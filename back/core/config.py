import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR=Path(__file__).resolve().parent.parent
ENV_FILE=BASE_DIR/"pass.env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE,override=False)

PG_CONNECTION_STRING=os.getenv("PG_CONNECTION_STRING")
JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM=os.getenv("JWT_ALGORITHM","HS256")
JWT_EXPIRE_MINUTES=int(os.getenv("JWT_EXPIRE_MINUTES","60"))

HAPI_FHIR_URL=os.getenv(
    "HAPI_FHIR_URL",
    "http://localhost:8080/fhir"
).rstrip("/")

if not PG_CONNECTION_STRING:
    raise RuntimeError("Falta PG_CONNECTION_STRING")

if not JWT_SECRET_KEY:
    raise RuntimeError("Falta JWT_SECRET_KEY")
