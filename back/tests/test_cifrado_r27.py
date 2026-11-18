"""Pruebas puras de R27 (cifrado AES-GCM). No usan base de datos ni red.

Desde back/:  python -m pytest tests/test_cifrado_r27.py -q
"""
import pytest

from core import cifrado as c


@pytest.fixture(autouse=True)
def llave(monkeypatch):
    monkeypatch.setenv("CIFRADO_LLAVE_K1", c.generar_llave())


def test_ida_y_vuelta():
    guardado = c.cifrar("3001234567", "telefono")
    assert guardado != "3001234567"
    assert c.descifrar(guardado, "telefono") == "3001234567"


def test_formato_version_llave_nonce_cifrado():
    partes = c.cifrar("Calle 5 # 10-20", "direccion").split(".")
    assert partes[0] == "v1" and partes[1] == "k1" and len(partes) == 4


def test_el_texto_original_no_aparece_en_lo_guardado():
    assert "3001234567" not in c.cifrar("3001234567", "telefono")


def test_mismo_valor_da_cifrados_distintos():
    # Nonce aleatorio: no se puede saber si dos pacientes comparten teléfono.
    assert c.cifrar("3001234567", "x") != c.cifrar("3001234567", "x")


def test_valor_alterado_se_rechaza():
    guardado = c.cifrar("3001234567", "telefono")
    alterado = guardado[:-2] + ("AA" if not guardado.endswith("AA") else "BB")
    with pytest.raises(c.ErrorCifrado):
        c.descifrar(alterado, "telefono")


def test_valor_copiado_a_otro_campo_no_descifra():
    # El nombre del campo va como dato asociado (AAD).
    guardado = c.cifrar("3001234567", "telefono")
    with pytest.raises(c.ErrorCifrado):
        c.descifrar(guardado, "direccion")


def test_con_otra_llave_no_descifra(monkeypatch):
    guardado = c.cifrar("3001234567", "x")
    monkeypatch.setenv("CIFRADO_LLAVE_K1", c.generar_llave())
    with pytest.raises(c.ErrorCifrado):
        c.descifrar(guardado, "x")


@pytest.mark.parametrize("vacio", [None, ""])
def test_vacios_no_se_cifran(vacio):
    assert c.cifrar(vacio, "x") == vacio
    assert c.descifrar(vacio, "x") == vacio


def test_dato_antiguo_sin_cifrar_se_devuelve_igual():
    assert c.descifrar("3001234567", "x") == "3001234567"


def test_no_se_cifra_dos_veces():
    una = c.cifrar("3001234567", "x")
    assert c.cifrar(una, "x") == una


def test_sin_llave_falla(monkeypatch):
    monkeypatch.delenv("CIFRADO_LLAVE_K1")
    with pytest.raises(c.ErrorCifrado):
        c.cifrar("3001234567", "x")


def test_llave_de_tamano_incorrecto_falla(monkeypatch):
    monkeypatch.setenv("CIFRADO_LLAVE_K1", "YWJj")
    with pytest.raises(c.ErrorCifrado):
        c.cifrar("3001234567", "x")


def test_acentos_y_longitud_maxima():
    direccion = "Carrera 100 # 5-169, Torre Ñandú, apto 301 — Cali " * 4
    direccion = direccion[:200]
    guardado = c.cifrar(direccion, "direccion")
    assert c.descifrar(guardado, "direccion") == direccion


def test_cifrar_campos_solo_toca_telefono_y_direccion():
    fila = {"nombres": "Ana", "telefono": "3001234567", "direccion": "Calle 5", "municipio_residencia": "Cali"}
    cifrada = c.cifrar_campos(fila)
    assert cifrada["nombres"] == "Ana" and cifrada["municipio_residencia"] == "Cali"
    assert c.esta_cifrado(cifrada["telefono"]) and c.esta_cifrado(cifrada["direccion"])
    assert fila["telefono"] == "3001234567"          # no modifica el original


def test_descifrar_fila_devuelve_los_valores_originales():
    fila = c.cifrar_campos({"telefono": "3001234567", "direccion": "Calle 5", "otro": 1})
    assert c.descifrar_fila(fila) == {"telefono": "3001234567", "direccion": "Calle 5", "otro": 1}


def test_descifrar_fila_sin_llave_no_revela_ni_se_cae(monkeypatch):
    fila = c.cifrar_campos({"telefono": "3001234567"})
    monkeypatch.delenv("CIFRADO_LLAVE_K1")
    resultado = c.descifrar_fila(dict(fila))
    assert resultado["telefono"] == fila["telefono"] and "3001234567" not in resultado["telefono"]


def test_descifrar_fila_acepta_none_y_filas_sin_esos_campos():
    assert c.descifrar_fila(None) is None
    assert c.descifrar_fila({"nombres": "Ana"}) == {"nombres": "Ana"}
