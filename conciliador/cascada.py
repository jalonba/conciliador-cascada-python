"""Orquestación de la cascada C1 → C5.

Cada capa solo recibe las filas que las anteriores no resolvieron: una fila
resuelta nunca baja a la siguiente. Lo que ninguna capa resuelve sale con
estado ``REVISAR_SCORE_BAJO`` y el mejor candidato semántico encontrado (si lo
hubo), para revisión humana.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from conciliador import capas

CAPAS = ("C1", "C2", "C3", "C4", "C5")
ESTADO_CONCILIADO = "CONCILIADO"
ESTADO_REVISAR = "REVISAR_SCORE_BAJO"

# capa → (columna del facturado que consume, columna del catálogo, umbral)
_SEMANTICAS = {
    "C3": ("procedimiento", capas.UMBRAL_C3),
    "C4": ("detalle", capas.UMBRAL_C4),
    "C5": ("observacion", capas.UMBRAL_C5),
}

UMBRALES = {"C1": capas.SCORE_C1, "C2": capas.SCORE_C2, **{k: v[1] for k, v in _SEMANTICAS.items()}}


@dataclass
class ResultadoCascada:
    filas: pd.DataFrame
    resumen: pd.DataFrame
    tiempos: dict[str, float] = field(default_factory=dict)


def _columna(df: pd.DataFrame, nombre: str) -> pd.Series:
    if nombre in df.columns:
        return df[nombre]
    return pd.Series([""] * len(df), index=df.index, dtype=object)


def _validar(facturado: pd.DataFrame, catalogo: pd.DataFrame) -> None:
    if "codigo" not in facturado.columns:
        raise ValueError("El facturado debe tener la columna 'codigo'.")
    if "codigo" not in catalogo.columns:
        raise ValueError("El catálogo debe tener la columna 'codigo'.")


def _ejecutar_capa(nombre: str, valores: pd.Series, catalogo: pd.DataFrame) -> pd.DataFrame:
    # Se llama vía el módulo ``capas`` para que cada capa sea sustituible/espiable.
    if nombre == "C1":
        return capas.capa_c1(valores, catalogo)
    if nombre == "C2":
        return capas.capa_c2(valores, catalogo)
    if nombre == "C3":
        return capas.capa_c3(valores, catalogo)
    if nombre == "C4":
        return capas.capa_c4(valores, catalogo)
    return capas.capa_c5(valores, catalogo)


def _resumen(filas: pd.DataFrame) -> pd.DataFrame:
    total = len(filas)
    conteos = filas.loc[filas["estado"] == ESTADO_CONCILIADO, "capa"].value_counts()
    registros = [(c, int(conteos.get(c, 0))) for c in CAPAS]
    registros.append((ESTADO_REVISAR, int((filas["estado"] == ESTADO_REVISAR).sum())))
    registros.append(("TOTAL", total))
    resumen = pd.DataFrame(registros, columns=["resultado", "filas"])
    resumen["porcentaje"] = (resumen["filas"] / total * 100).round(2) if total else 0.0
    return resumen


def conciliar(facturado: pd.DataFrame, catalogo: pd.DataFrame) -> ResultadoCascada:
    """Concilia ``facturado`` contra ``catalogo`` con la cascada de cinco capas."""
    _validar(facturado, catalogo)
    catalogo = catalogo.reset_index(drop=True)
    filas = facturado.copy()
    n = len(filas)

    estado = np.full(n, ESTADO_REVISAR, dtype=object)
    capa = np.full(n, None, dtype=object)
    score = np.full(n, np.nan, dtype=float)
    candidato_pos = np.full(n, -1, dtype=np.int64)
    capa_candidato = np.full(n, None, dtype=object)
    pendiente = np.ones(n, dtype=bool)
    tiempos: dict[str, float] = {}

    for nombre in CAPAS:
        inicio = time.perf_counter()
        idx = np.flatnonzero(pendiente)
        if idx.size:
            campo = "codigo" if nombre in ("C1", "C2") else _SEMANTICAS[nombre][0]
            valores = _columna(filas, campo).iloc[idx]
            r = _ejecutar_capa(nombre, valores, catalogo)
            resuelto = r["resuelto"].to_numpy(dtype=bool)
            r_score = r["score"].to_numpy(dtype=float)
            r_pos = r["candidato_pos"].fillna(-1).to_numpy(dtype=np.int64)

            ok = idx[resuelto]
            estado[ok] = ESTADO_CONCILIADO
            capa[ok] = nombre
            score[ok] = r_score[resuelto]
            candidato_pos[ok] = r_pos[resuelto]
            capa_candidato[ok] = nombre
            pendiente[ok] = False

            # Mejor candidato no resuelto: se guarda para revisión humana.
            mejora = ~resuelto & (r_pos >= 0) & ~(r_score <= score[idx])
            mej = idx[mejora]
            score[mej] = r_score[mejora]
            candidato_pos[mej] = r_pos[mejora]
            capa_candidato[mej] = nombre
        tiempos[nombre] = time.perf_counter() - inicio

    codigos_cat = catalogo["codigo"].to_numpy(dtype=object)
    procs_cat = _columna(catalogo, "procedimiento").to_numpy(dtype=object)
    tiene = candidato_pos >= 0
    candidato = np.full(n, None, dtype=object)
    candidato_proc = np.full(n, None, dtype=object)
    candidato[tiene] = codigos_cat[candidato_pos[tiene]]
    candidato_proc[tiene] = procs_cat[candidato_pos[tiene]]

    def objeto(valores: np.ndarray) -> pd.Series:
        # dtype object explícito: conserva ``None`` (pandas 3 inferiría str con NaN).
        return pd.Series(valores, index=filas.index, dtype=object)

    filas["estado"] = objeto(estado)
    filas["capa"] = objeto(capa)
    filas["score"] = score
    filas["candidato"] = objeto(candidato)
    filas["capa_candidato"] = objeto(capa_candidato)
    filas["candidato_procedimiento"] = objeto(candidato_proc)
    return ResultadoCascada(filas=filas, resumen=_resumen(filas), tiempos=tiempos)
