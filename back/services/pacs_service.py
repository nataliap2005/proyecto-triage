# Servicio encargado de la comunicación entre FastAPI y Orthanc.
# Centraliza las operaciones PACS/DICOM como verificación del servicio,
# carga de imágenes, consulta de estudios e instancias, lectura de metadatos
# y generación de previews, evitando que los routers accedan directamente a Orthanc.

import os
from typing import Any

import requests
from fastapi import HTTPException

ORTHANC_URL = os.getenv("ORTHANC_URL", "http://localhost:8042").rstrip("/")
ORTHANC_USERNAME = os.getenv("ORTHANC_USERNAME", "orthanc")
ORTHANC_PASSWORD = os.getenv("ORTHANC_PASSWORD", "orthanc")
ORTHANC_TIMEOUT = 25


def _request(method: str, path: str, *, expected: tuple[int, ...] = (200,), **kwargs) -> requests.Response:
    try:
        response = requests.request(
            method,
            f"{ORTHANC_URL}{path}",
            auth=(ORTHANC_USERNAME, ORTHANC_PASSWORD),
            timeout=ORTHANC_TIMEOUT,
            **kwargs
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PACS Orthanc no disponible: {exc}"
        )

    if response.status_code not in expected:
        try:
            detalle: Any = response.json()
        except ValueError:
            detalle = response.text

        raise HTTPException(
            status_code=502,
            detail={
                "mensaje": "Orthanc rechazó la operación",
                "status_code": response.status_code,
                "respuesta": detalle
            }
        )

    return response


def estado_pacs() -> dict:
    response = _request("GET", "/system")
    data = response.json()

    return {
        "estado": "ok",
        "url_interna": ORTHANC_URL,
        "nombre": data.get("Name"),
        "version": data.get("Version"),
        "dicom_aet": data.get("DicomAet")
    }


def subir_instancia_dicom(contenido: bytes) -> dict:
    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo DICOM está vacío")

    response = _request(
        "POST",
        "/instances",
        expected=(200, 201),
        data=contenido,
        headers={"Content-Type": "application/dicom"}
    )

    data = response.json()

    instance_id = data.get("ID")
    study_id = data.get("ParentStudy")

    if not instance_id or not study_id:
        raise HTTPException(
            status_code=502,
            detail="Orthanc recibió el archivo pero no devolvió ID/ParentStudy"
        )

    return data


def obtener_instancia(instance_id: str) -> dict:
    return _request("GET", f"/instances/{instance_id}").json()


def obtener_tags_instancia(instance_id: str) -> dict:
    return _request("GET", f"/instances/{instance_id}/simplified-tags").json()


def obtener_estudio_orthanc(study_id: str) -> dict:
    return _request("GET", f"/studies/{study_id}").json()


def obtener_instancias_estudio(study_id: str) -> list[dict]:
    study = obtener_estudio_orthanc(study_id)
    resultados = []

    for series_id in study.get("Series", []):
        serie = _request("GET", f"/series/{series_id}").json()

        for instance_id in serie.get("Instances", []):
            resultados.append({
                "series_id": series_id,
                "instance_id": instance_id
            })

    return resultados


def obtener_preview_instancia(instance_id: str) -> tuple[bytes, str]:
    response = _request("GET", f"/instances/{instance_id}/preview")
    content_type = response.headers.get("Content-Type", "image/png")
    return response.content, content_type


def eliminar_instancia(instance_id: str) -> None:
    _request("DELETE", f"/instances/{instance_id}", expected=(200,))


def extraer_metadatos_subida(resultado_subida: dict) -> dict:
    instance_id = resultado_subida["ID"]
    study_id = resultado_subida["ParentStudy"]

    tags_instancia = obtener_tags_instancia(instance_id)
    estudio = obtener_estudio_orthanc(study_id)
    tags_estudio = estudio.get("MainDicomTags", {})

    study_instance_uid = (
        tags_estudio.get("StudyInstanceUID")
        or tags_instancia.get("StudyInstanceUID")
    )

    if not study_instance_uid:
        raise HTTPException(
            status_code=422,
            detail="El DICOM no contiene StudyInstanceUID utilizable"
        )

    study_date = tags_estudio.get("StudyDate") or tags_instancia.get("StudyDate")
    study_time = tags_estudio.get("StudyTime") or tags_instancia.get("StudyTime")

    return {
        "instance_id": instance_id,
        "orthanc_study_id": study_id,
        "study_instance_uid": study_instance_uid,
        "modalidad": tags_instancia.get("Modality"),
        "study_description": (
            tags_estudio.get("StudyDescription")
            or tags_instancia.get("StudyDescription")
        ),
        "study_date": study_date,
        "study_time": study_time,
        "patient_id_dicom": tags_instancia.get("PatientID")
    }
