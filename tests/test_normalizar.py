import math
import re

import pytest

from conciliador.normalizar import normalizar_codigo, normalizar_texto

# ---------------------------------------------------------------- códigos


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("123456", "123456"),
        ("  123456  ", "123456"),
        ("012345", "12345"),  # ceros a la izquierda
        ("12345", "12345"),
        ("0012345", "12345"),
        ("12-34-56", "123456"),  # guiones
        ("12.34.56", "123456"),  # puntos
        ("12 34 56", "123456"),  # espacios internos
        ("12_34/56", "123456"),  # otros separadores
        ("3q2714", "3Q2714"),  # minúsculas → mayúsculas
    ],
)
def test_normalizar_codigo_casos_basicos(crudo, esperado):
    assert normalizar_codigo(crudo) == esperado


def test_codigo_alfanumerico_no_se_descarta():
    """Una regex ``^\\d{6}$`` descartaría en silencio este código; la normalización no."""
    crudo = "47K8-15"
    assert re.fullmatch(r"^\d{6}$", crudo.replace("-", "")) is None  # la trampa existe
    assert normalizar_codigo(crudo) == "47K815"


@pytest.mark.parametrize("crudo", ["0A1234", "a01234", "00a123"])
def test_codigo_alfanumerico_con_ceros(crudo):
    resultado = normalizar_codigo(crudo)
    assert resultado != ""
    assert resultado[0] != "0"
    assert resultado.isupper()


def test_codigo_numerico_leido_como_float():
    # Excel suele entregar 123456 como 123456.0
    assert normalizar_codigo(123456.0) == "123456"
    assert normalizar_codigo(12345) == "12345"


@pytest.mark.parametrize("vacio", [None, "", "   ", math.nan, "-", "--"])
def test_codigo_vacio_devuelve_cadena_vacia(vacio):
    assert normalizar_codigo(vacio) == ""


def test_codigo_solo_ceros_no_queda_vacio():
    assert normalizar_codigo("000000") == "0"


def test_codigo_con_tildes():
    assert normalizar_codigo("ñ12345") == "N12345"


# ----------------------------------------------------------------- textos


def test_texto_mayusculas_y_tildes():
    assert normalizar_texto("Ecografía de tórax") == "ECOGRAFIA DE TORAX"


def test_texto_espacios_y_puntuacion():
    assert normalizar_texto("  rx.   de   torax,  (pa/lat) ") == "RX DE TORAX PA LAT"


def test_texto_enie():
    assert normalizar_texto("Señal") == "SENAL"


@pytest.mark.parametrize("vacio", [None, "", "   ", math.nan])
def test_texto_vacio(vacio):
    assert normalizar_texto(vacio) == ""


def test_texto_numero():
    assert normalizar_texto(3.0) == "3"
    assert normalizar_texto(12) == "12"
