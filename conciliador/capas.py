"""Las cinco capas de la cascada.

Cada capa recibe una ``Series`` de valores del facturado (código o texto,
según la capa) y el catálogo, y devuelve un ``DataFrame`` con el mismo índice
y las columnas:

* ``candidato``: código del catálogo propuesto (``None`` si no hay).
* ``candidato_pos``: posición (0..n-1) del candidato en el catálogo.
* ``score``: confianza de la capa (``NaN`` si no hay candidato).
* ``resuelto``: ``True`` solo si el candidato supera la regla de la capa.

Una capa nunca marca como resuelto un candidato ambiguo ni uno bajo umbral.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd

from conciliador.normalizar import normalizar_codigo

SCORE_C1 = 1.0
SCORE_C2 = 0.95

COLUMNAS_RESULTADO = ["candidato", "candidato_pos", "score", "resuelto"]


def resultado_vacio(indice: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "candidato": pd.Series([None] * len(indice), index=indice, dtype=object),
            "candidato_pos": pd.Series(pd.NA, index=indice, dtype="Int64"),
            "score": pd.Series(np.nan, index=indice, dtype=float),
            "resuelto": pd.Series(False, index=indice, dtype=bool),
        }
    )


def _indice_unico(claves: Iterable[str]) -> dict[str, int]:
    """Mapa clave → posición, solo para claves no vacías que aparecen una vez."""
    claves = list(claves)
    conteo = Counter(claves)
    return {k: i for i, k in enumerate(claves) if k and conteo[k] == 1}


def _capa_por_clave(
    valores: pd.Series,
    catalogo: pd.DataFrame,
    clave: Callable[[object], str],
    score: float,
) -> pd.DataFrame:
    resultado = resultado_vacio(valores.index)
    if valores.empty:
        return resultado
    indice = _indice_unico(clave(c) for c in catalogo["codigo"])
    posiciones = [indice.get(clave(v)) for v in valores]
    encontrados = np.array([p is not None for p in posiciones], dtype=bool)
    if not encontrados.any():
        return resultado
    pos = np.array([p for p in posiciones if p is not None], dtype=np.int64)
    codigos = catalogo["codigo"].to_numpy(dtype=object)
    filas = resultado.index[encontrados]
    resultado.loc[filas, "candidato"] = codigos[pos]
    resultado.loc[filas, "candidato_pos"] = pos
    resultado.loc[filas, "score"] = score
    resultado.loc[filas, "resuelto"] = True
    return resultado


def _clave_exacta(valor: object) -> str:
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return ""
    return str(valor).strip()


def capa_c1(codigos: pd.Series, catalogo: pd.DataFrame) -> pd.DataFrame:
    """C1 · código exacto (solo se recortan espacios alrededor)."""
    return _capa_por_clave(codigos, catalogo, _clave_exacta, SCORE_C1)


def capa_c2(codigos: pd.Series, catalogo: pd.DataFrame) -> pd.DataFrame:
    """C2 · código normalizado (mayúsculas, sin separadores ni ceros a la izquierda)."""
    return _capa_por_clave(codigos, catalogo, normalizar_codigo, SCORE_C2)

