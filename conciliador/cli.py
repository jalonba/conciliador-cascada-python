"""Interfaz de línea de comandos.

python -m conciliador --facturado facturado.csv --catalogo catalogo.csv --salida salida/
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

from conciliador.cascada import conciliar
from conciliador.reportes import exportar, tabla_resumen


def leer_tabla(ruta: Path) -> pd.DataFrame:
    """Lee CSV o Excel como texto (los códigos conservan sus ceros a la izquierda)."""
    sufijo = ruta.suffix.lower()
    if sufijo == ".csv":
        return pd.read_csv(ruta, dtype=str, keep_default_na=False)
    if sufijo in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(ruta, dtype=str, keep_default_na=False)
    raise ValueError(f"formato no soportado: {ruta.name} (use .csv o .xlsx)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="conciliador", description="Conciliación de registros en cascada de 5 capas."
    )
    parser.add_argument("--facturado", type=Path, required=True, help="CSV/XLSX a conciliar")
    parser.add_argument("--catalogo", type=Path, required=True, help="CSV/XLSX de referencia")
    parser.add_argument("--salida", type=Path, required=True, help="carpeta de resultados")
    args = parser.parse_args(argv)

    for ruta in (args.facturado, args.catalogo):
        if not ruta.is_file():
            print(f"error: el archivo {ruta} no existe", file=sys.stderr)
            return 2
    try:
        facturado = leer_tabla(args.facturado)
        catalogo = leer_tabla(args.catalogo)
        inicio = time.perf_counter()
        resultado = conciliar(facturado, catalogo)
        segundos = time.perf_counter() - inicio
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    conciliado, auditoria = exportar(resultado, args.salida)
    print(tabla_resumen(resultado).to_string(index=False))
    print(f"\n{len(facturado):,} filas conciliadas en {segundos:.1f} s")
    print(f"→ {conciliado}\n→ {auditoria}")
    return 0
