"""Benchmark de la cascada sobre datos sintéticos con verdad de terreno.

Mide, por capa, cuántas filas resuelve, qué porcentaje del total representan y
su precisión (candidato == código verdadero), además del porcentaje que queda
para revisión, los falsos positivos sobre filas sin pareja real y el tiempo.

    python -m benchmark.correr --filas 250000 --semilla 42
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from conciliador.cascada import CAPAS, ESTADO_CONCILIADO, ESTADO_REVISAR, UMBRALES, conciliar
from conciliador.reportes import exportar
from datos.generar_sinteticos import ESCENARIOS, generar

SALIDA_MD = Path(__file__).with_name("resultados.md")


def _pct(parte: float, total: float) -> float:
    return float(parte) / total * 100 if total else float("nan")


def metricas(filas: pd.DataFrame) -> dict:
    total = len(filas)
    conciliada = (filas["estado"] == ESTADO_CONCILIADO).to_numpy()
    verdad = filas["_codigo_verdadero"].fillna("").astype(str).to_numpy()
    candidato = filas["candidato"].to_numpy(dtype=object)
    con_pareja = verdad != ""
    correcta = conciliada & con_pareja & (candidato == verdad)
    capa = filas["capa"].to_numpy(dtype=object)

    registros = []
    for c in CAPAS:
        en_capa = conciliada & (capa == c)
        n = int(en_capa.sum())
        registros.append(
            (c, n, _pct(n, total), _pct(int((correcta & en_capa).sum()), n), UMBRALES[c])
        )
    revisar = int((~conciliada).sum())
    registros.append((ESTADO_REVISAR, revisar, _pct(revisar, total), float("nan"), float("nan")))
    registros.append(
        ("TOTAL", total, _pct(total, total), _pct(int(correcta.sum()), int(conciliada.sum())), "")
    )
    por_capa = pd.DataFrame(
        registros, columns=["resultado", "filas", "porcentaje", "precision", "umbral"]
    )

    escenario = filas["_escenario"].to_numpy(dtype=object)
    sin_pareja = ~con_pareja
    esc_registros = []
    for e in ESCENARIOS:
        en = escenario == e
        n = int(en.sum())
        if not n:
            continue
        # «correcto»: con pareja → conciliado al código verdadero; sin pareja → enviado a revisión
        ok = (correcta & en) if not e.startswith("sin_pareja") else (~conciliada & en)
        esc_registros.append((e, n, _pct(int((conciliada & en).sum()), n), _pct(int(ok.sum()), n)))
    por_escenario = pd.DataFrame(
        esc_registros, columns=["escenario", "filas", "conciliado_pct", "correcto_pct"]
    )

    n_conciliadas = int(conciliada.sum())
    globales = {
        "filas": total,
        "resuelto_pct": _pct(n_conciliadas, total),
        "revisar_pct": _pct(revisar, total),
        "precision_resueltas_pct": _pct(int(correcta.sum()), n_conciliadas),
        "errores_resueltas": n_conciliadas - int(correcta.sum()),
        "sin_pareja": int(sin_pareja.sum()),
        "sin_pareja_conciliadas": int((sin_pareja & conciliada).sum()),
    }
    return {"por_capa": por_capa, "global": globales, "por_escenario": por_escenario}


def _num(x: float, decimales: int = 1) -> str:
    if isinstance(x, float) and np.isnan(x):
        return "—"
    return f"{x:,.{decimales}f}"


def tabla_markdown(m: dict, filas: int, semilla: int, items_catalogo: int) -> str:
    g, t = m["global"], m["tiempos"]
    lineas = [
        "# Resultados del benchmark sintético",
        "",
        f"Generado con `python -m benchmark.correr --filas {filas} --semilla {semilla} "
        f"--items-catalogo {items_catalogo}`.",
        "",
        f"- Filas facturadas: **{g['filas']:,}** · ítems de catálogo: **{items_catalogo:,}**",
        f"- Entorno: Python {platform.python_version()} · pandas {pd.__version__} · "
        f"scikit-learn {sklearn.__version__} · {os.cpu_count()} núcleos lógicos · "
        f"{platform.system()}",
        "",
        "## Resolución por capa",
        "",
        "| Capa | Umbral | Filas | % del total | Precisión |",
        "|---|---|---:|---:|---:|",
    ]
    for r in m["por_capa"].itertuples(index=False):
        umbral = f"{r.umbral:.2f}" if isinstance(r.umbral, float) and not np.isnan(r.umbral) else ""
        lineas.append(
            f"| {r.resultado} | {umbral} | {r.filas:,} | {_num(r.porcentaje)} % | "
            f"{_num(r.precision)}{' %' if not np.isnan(r.precision) else ''} |"
        )
    lineas += [
        "",
        "Precisión = filas cuyo candidato coincide con el código verdadero ÷ filas resueltas "
        "por la capa (las filas sin pareja que se concilian cuentan como error).",
        "",
        "## Resumen",
        "",
        f"- Resuelto automáticamente: **{_num(g['resuelto_pct'])} %**",
        f"- A revisión humana (`REVISAR_SCORE_BAJO`): **{_num(g['revisar_pct'])} %**",
        f"- Precisión de lo resuelto: **{_num(g['precision_resueltas_pct'], 2)} %** "
        f"({g['errores_resueltas']:,} filas con candidato equivocado)",
        f"- Filas sin pareja real: {g['sin_pareja']:,}, de las cuales "
        f"**{g['sin_pareja_conciliadas']:,}** se conciliaron por error",
        f"- Tiempo de la cascada: **{t['cascada']:.2f} s** "
        f"(generación de datos: {t['generacion']:.2f} s"
        + (f"; exportación Excel: {t['excel']:.2f} s" if "excel" in t else "")
        + ")",
        "",
        "## Por escenario de ruido",
        "",
        "| Escenario | Filas | % conciliado | % correcto |",
        "|---|---:|---:|---:|",
    ]
    for r in m["por_escenario"].itertuples(index=False):
        lineas.append(
            f"| {r.escenario} | {r.filas:,} | {_num(r.conciliado_pct)} % | "
            f"{_num(r.correcto_pct)} % |"
        )
    lineas += [
        "",
        "«% correcto»: con pareja → conciliado al código verdadero; sin pareja → enviado a "
        "revisión.",
        "",
        "## Tiempo por capa",
        "",
        "| Capa | Segundos |",
        "|---|---:|",
    ]
    lineas += [f"| {c} | {t[c]:.2f} |" for c in CAPAS if c in t]
    return "\n".join(lineas) + "\n"


def correr(
    filas: int = 250_000,
    semilla: int = 42,
    items_catalogo: int = 6000,
    salida_md: Path | None = SALIDA_MD,
    excel_dir: Path | None = None,
) -> dict:
    inicio = time.perf_counter()
    catalogo, facturado = generar(filas, semilla, items_catalogo)
    t_gen = time.perf_counter() - inicio

    inicio = time.perf_counter()
    resultado = conciliar(facturado, catalogo)
    t_cascada = time.perf_counter() - inicio

    m = metricas(resultado.filas)
    m["tiempos"] = {"generacion": t_gen, "cascada": t_cascada, **resultado.tiempos}
    if excel_dir is not None:
        inicio = time.perf_counter()
        exportar(resultado, excel_dir)
        m["tiempos"]["excel"] = time.perf_counter() - inicio
    if salida_md is not None:
        Path(salida_md).write_text(
            tabla_markdown(m, filas, semilla, items_catalogo), encoding="utf-8"
        )
    return m


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark de la cascada sobre datos sintéticos.")
    parser.add_argument("--filas", type=int, default=250_000)
    parser.add_argument("--semilla", type=int, default=42)
    parser.add_argument("--items-catalogo", type=int, default=6000)
    parser.add_argument("--salida-md", type=Path, default=SALIDA_MD)
    parser.add_argument("--excel", type=Path, default=None, help="carpeta para exportar Excel")
    args = parser.parse_args(argv)
    correr(args.filas, args.semilla, args.items_catalogo, args.salida_md, args.excel)
    sys.stdout.write(args.salida_md.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
