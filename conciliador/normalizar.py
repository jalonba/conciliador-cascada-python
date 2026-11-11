"""Normalización de códigos y textos antes de comparar.

Las reglas son deliberadamente conservadoras: no se descarta ningún carácter
alfanumérico, de modo que un código como ``89A201`` sobrevive intacto (una
validación ingenua tipo ``^\\d{6}$`` lo perdería en silencio).
"""

from __future__ import annotations

import math
import re
import unicodedata

_NO_ALFANUMERICO = re.compile(r"[^0-9A-Z]+")
_ESPACIOS = re.compile(r"\s+")


def _es_vacio(valor: object) -> bool:
    if valor is None:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    return False


def _a_cadena(valor: object) -> str:
    """Convierte a ``str`` tratando ``123456.0`` (típico de Excel) como ``123456``."""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def quitar_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def normalizar_texto(valor: object) -> str:
    """Mayúsculas, sin tildes, sin puntuación y con espacios colapsados."""
    if _es_vacio(valor):
        return ""
    texto = quitar_tildes(_a_cadena(valor)).upper()
    texto = _NO_ALFANUMERICO.sub(" ", texto)
    return _ESPACIOS.sub(" ", texto).strip()


def normalizar_codigo(valor: object) -> str:
    """Forma canónica de un código para la capa C2.

    Mayúsculas, sin tildes, sin separadores (guiones, puntos, espacios, barras)
    y sin ceros a la izquierda. Un código formado solo por ceros queda ``"0"``.
    """
    if _es_vacio(valor):
        return ""
    codigo = quitar_tildes(_a_cadena(valor)).upper()
    codigo = _NO_ALFANUMERICO.sub("", codigo)
    if not codigo:
        return ""
    return codigo.lstrip("0") or "0"
