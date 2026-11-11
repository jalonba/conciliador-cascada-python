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
from collections.abc import Callable, Iterable, Sequence

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer

from conciliador.normalizar import normalizar_codigo, normalizar_texto

SCORE_C1 = 1.0
SCORE_C2 = 0.95
UMBRAL_C3 = 0.55
UMBRAL_C4 = 0.55
UMBRAL_C5 = 0.50

TOP_K = 5
MARGEN_EMPATE = 0.02
TAMANO_LOTE = 2000

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


# ------------------------------------------------------------ capas semánticas


def desempatar(
    consulta: str, candidatos: Sequence[tuple[int, float, str]], margen: float = MARGEN_EMPATE
) -> int:
    """Elige entre ``(pos, score_tfidf, texto)`` los que están a ``margen`` del mejor.

    Entre los empatados gana el de mayor ``rapidfuzz.fuzz.token_sort_ratio``
    contra la consulta; si persiste el empate, el de mayor score y luego la
    menor posición (determinista).
    """
    mejor = max(c[1] for c in candidatos)
    empatados = [c for c in candidatos if c[1] >= mejor - margen - 1e-12]
    if len(empatados) == 1:
        return empatados[0][0]
    return min(empatados, key=lambda c: (-fuzz.token_sort_ratio(consulta, c[2]), -c[1], c[0]))[0]


class IndiceSemantico:
    """Índice TF-IDF de n-gramas de caracteres sobre una columna del catálogo.

    Los textos del catálogo se normalizan y se deduplican: un texto que aparece
    en más de un ítem queda marcado como ambiguo. Los vacíos no se indexan.
    """

    def __init__(
        self,
        textos_catalogo: Iterable[object],
        *,
        top_k: int = TOP_K,
        margen_empate: float = MARGEN_EMPATE,
        tamano_lote: int = TAMANO_LOTE,
    ) -> None:
        self.top_k = top_k
        self.margen_empate = margen_empate
        self.tamano_lote = max(1, tamano_lote)

        primera_pos: dict[str, int] = {}
        repeticiones: Counter[str] = Counter()
        for pos, texto in enumerate(textos_catalogo):
            norm = normalizar_texto(texto)
            if not norm:
                continue
            repeticiones[norm] += 1
            primera_pos.setdefault(norm, pos)

        self.textos = list(primera_pos)
        self.posiciones = np.array([primera_pos[t] for t in self.textos], dtype=np.int64)
        self.ambiguos = np.array([repeticiones[t] > 1 for t in self.textos], dtype=bool)
        self.vectorizador: TfidfVectorizer | None = None
        if self.textos:
            self.vectorizador = TfidfVectorizer(
                analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True, dtype=np.float32
            )
            self.matriz_t = self.vectorizador.fit_transform(self.textos).T.tocsr()

    def buscar(self, textos: pd.Series) -> pd.DataFrame:
        """Mejor candidato por fila: ``candidato_pos``, ``score`` y ``ambiguo``."""
        n = len(textos)
        pos_out = np.full(n, -1, dtype=np.int64)
        score_out = np.full(n, np.nan, dtype=float)
        ambiguo_out = np.zeros(n, dtype=bool)

        consultas = [normalizar_texto(t) for t in textos]
        filas = [i for i, c in enumerate(consultas) if c]
        if self.vectorizador is not None and filas:
            k = min(self.top_k, len(self.textos))
            for inicio in range(0, len(filas), self.tamano_lote):
                lote = filas[inicio : inicio + self.tamano_lote]
                q = self.vectorizador.transform([consultas[i] for i in lote])
                sim = (q @ self.matriz_t).toarray()
                if k < sim.shape[1]:
                    top = np.argpartition(-sim, k - 1, axis=1)[:, :k]
                else:
                    top = np.tile(np.arange(sim.shape[1]), (len(lote), 1))
                for j, i in enumerate(lote):
                    candidatos = [(int(u), float(sim[j, u]), self.textos[u]) for u in top[j]]
                    elegido = desempatar(consultas[i], candidatos, self.margen_empate)
                    score = min(float(sim[j, elegido]), 1.0)
                    if score <= 0.0:
                        continue
                    pos_out[i] = self.posiciones[elegido]
                    score_out[i] = score
                    ambiguo_out[i] = self.ambiguos[elegido]

        return pd.DataFrame(
            {
                "candidato_pos": pd.array([p if p >= 0 else pd.NA for p in pos_out], dtype="Int64"),
                "score": score_out,
                "ambiguo": ambiguo_out,
            },
            index=textos.index,
        )


def capa_semantica(
    textos: pd.Series,
    catalogo: pd.DataFrame,
    campo: str,
    umbral: float,
    indice: IndiceSemantico | None = None,
) -> pd.DataFrame:
    """Capa semántica genérica sobre ``campo``; resuelve si ``score >= umbral``."""
    resultado = resultado_vacio(textos.index)
    if textos.empty:
        return resultado
    if indice is None:
        columna = catalogo[campo] if campo in catalogo else pd.Series([""] * len(catalogo))
        indice = IndiceSemantico(columna)
    hallado = indice.buscar(textos)
    con_candidato = hallado["candidato_pos"].notna().to_numpy()
    if not con_candidato.any():
        return resultado
    filas = resultado.index[con_candidato]
    pos = hallado.loc[con_candidato, "candidato_pos"].to_numpy(dtype=np.int64)
    scores = hallado.loc[con_candidato, "score"].to_numpy()
    ambiguos = hallado.loc[con_candidato, "ambiguo"].to_numpy()
    resultado.loc[filas, "candidato"] = catalogo["codigo"].to_numpy(dtype=object)[pos]
    resultado.loc[filas, "candidato_pos"] = pos
    resultado.loc[filas, "score"] = scores
    resultado.loc[filas, "resuelto"] = (scores >= umbral) & ~ambiguos
    return resultado


def capa_c3(
    textos: pd.Series, catalogo: pd.DataFrame, indice: IndiceSemantico | None = None
) -> pd.DataFrame:
    """C3 · similitud sobre ``procedimiento`` (umbral 0,55)."""
    return capa_semantica(textos, catalogo, "procedimiento", UMBRAL_C3, indice)


def capa_c4(
    textos: pd.Series, catalogo: pd.DataFrame, indice: IndiceSemantico | None = None
) -> pd.DataFrame:
    """C4 · similitud sobre ``detalle`` (umbral 0,55)."""
    return capa_semantica(textos, catalogo, "detalle", UMBRAL_C4, indice)


def capa_c5(
    textos: pd.Series, catalogo: pd.DataFrame, indice: IndiceSemantico | None = None
) -> pd.DataFrame:
    """C5 · similitud sobre ``observacion`` (umbral 0,50)."""
    return capa_semantica(textos, catalogo, "observacion", UMBRAL_C5, indice)
