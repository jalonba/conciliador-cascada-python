"""Exportación a Excel: ``conciliado.xlsx`` y ``reporte_auditoria.xlsx``.

Se escribe con ``openpyxl`` en modo *write-only* para no cargar en memoria el
libro completo (cientos de miles de filas). Los textos que empiezan por ``=``
se guardan como texto, nunca como fórmula (evita inyección de fórmulas).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

from conciliador.cascada import (
    CAPAS,
    ESTADO_CONCILIADO,
    ESTADO_REVISAR,
    UMBRALES,
    ResultadoCascada,
)


def _valor(ws: WriteOnlyWorksheet, valor: object) -> object:
    if valor is None or valor is pd.NA:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    if isinstance(valor, np.generic):
        valor = valor.item()
    if isinstance(valor, str) and valor.startswith("="):
        celda = WriteOnlyCell(ws, value=valor)
        celda.data_type = "s"
        return celda
    return valor


def _escribir_hoja(libro: Workbook, nombre: str, df: pd.DataFrame) -> None:
    ws = libro.create_sheet(nombre)
    ws.append([str(c) for c in df.columns])
    for fila in df.itertuples(index=False, name=None):
        ws.append([_valor(ws, v) for v in fila])


def tabla_resumen(resultado: ResultadoCascada) -> pd.DataFrame:
    resumen = resultado.resumen.copy()
    resumen["umbral"] = resumen["resultado"].map(UMBRALES)
    resumen["segundos"] = resumen["resultado"].map(resultado.tiempos).round(3)
    total = sum(resultado.tiempos.get(c, 0.0) for c in CAPAS)
    resumen.loc[resumen["resultado"] == "TOTAL", "segundos"] = round(total, 3)
    return resumen


def exportar(resultado: ResultadoCascada, carpeta: str | Path) -> tuple[Path, Path]:
    """Escribe los dos libros en ``carpeta`` y devuelve sus rutas."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    filas = resultado.filas

    ruta_conciliado = carpeta / "conciliado.xlsx"
    libro = Workbook(write_only=True)
    _escribir_hoja(libro, "conciliado", filas)
    libro.save(ruta_conciliado)

    revisar = filas[filas["estado"] == ESTADO_REVISAR].sort_values(
        "score", ascending=False, na_position="last"
    )
    semanticas = filas[
        (filas["estado"] == ESTADO_CONCILIADO) & filas["capa"].isin(["C3", "C4", "C5"])
    ].sort_values("score", ascending=True)

    ruta_auditoria = carpeta / "reporte_auditoria.xlsx"
    libro = Workbook(write_only=True)
    _escribir_hoja(libro, "resumen", tabla_resumen(resultado))
    _escribir_hoja(libro, "revisar", revisar)
    _escribir_hoja(libro, "semanticas", semanticas)
    libro.save(ruta_auditoria)
    return ruta_conciliado, ruta_auditoria
