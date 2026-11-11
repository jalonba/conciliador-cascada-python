import math

import pandas as pd
import pytest

from conciliador.capas import SCORE_C1, SCORE_C2, capa_c1, capa_c2


@pytest.fixture
def catalogo():
    return pd.DataFrame(
        {
            "codigo": ["123456", "012345", "47K815", "777777", "777777", "5B0001"],
            "procedimiento": ["UNO", "DOS", "TRES", "CUATRO A", "CUATRO B", "CINCO"],
        }
    )


def _serie(valores, indice=None):
    return pd.Series(valores, index=indice, dtype=object)


# ---------------------------------------------------------------------- C1


def test_c1_resuelve_codigo_exacto(catalogo):
    r = capa_c1(_serie(["123456", "47K815"]), catalogo)
    assert r["resuelto"].tolist() == [True, True]
    assert r["candidato"].tolist() == ["123456", "47K815"]
    assert r["candidato_pos"].tolist() == [0, 2]
    assert (r["score"] == SCORE_C1).all()
    assert SCORE_C1 == 1.0


def test_c1_tolera_espacios_alrededor(catalogo):
    r = capa_c1(_serie(["  123456 "]), catalogo)
    assert r["resuelto"].iloc[0]


@pytest.mark.parametrize("variante", ["12-3456", "12345", "47k815", "0123456", "123456.0"])
def test_c1_no_resuelve_variantes_normalizables(catalogo, variante):
    """C1 es estricta: las variantes son trabajo de C2."""
    r = capa_c1(_serie([variante]), catalogo)
    assert not r["resuelto"].iloc[0]
    assert r["candidato"].iloc[0] is None
    assert math.isnan(r["score"].iloc[0])


@pytest.mark.parametrize("vacio", [None, "", math.nan])
def test_c1_vacios_no_resuelven(catalogo, vacio):
    assert not capa_c1(_serie([vacio]), catalogo)["resuelto"].iloc[0]


def test_c1_codigo_duplicado_en_catalogo_es_ambiguo(catalogo):
    r = capa_c1(_serie(["777777"]), catalogo)
    assert not r["resuelto"].iloc[0]


def test_c1_conserva_indice(catalogo):
    r = capa_c1(_serie(["123456", "000000"], indice=[10, 42]), catalogo)
    assert r.index.tolist() == [10, 42]
    assert r.loc[10, "resuelto"] and not r.loc[42, "resuelto"]


def test_c1_entrada_vacia(catalogo):
    r = capa_c1(_serie([]), catalogo)
    assert r.empty
    assert {"candidato", "candidato_pos", "score", "resuelto"} <= set(r.columns)


# ---------------------------------------------------------------------- C2


@pytest.mark.parametrize(
    ("variante", "esperado"),
    [
        ("12-34-56", "123456"),
        ("12.34.56", "123456"),
        ("12345", "012345"),  # se perdió el cero a la izquierda
        ("0012345", "012345"),  # sobra un cero
        ("47k8-15", "47K815"),  # alfanumérico en minúsculas con guion
        ("5b0001", "5B0001"),
        (123456.0, "123456"),  # leído como float desde Excel
    ],
)
def test_c2_resuelve_variantes(catalogo, variante, esperado):
    r = capa_c2(_serie([variante]), catalogo)
    assert r["resuelto"].iloc[0]
    assert r["candidato"].iloc[0] == esperado
    assert r["score"].iloc[0] == SCORE_C2
    assert SCORE_C2 == 0.95


def test_c2_no_inventa_codigo_distinto(catalogo):
    r = capa_c2(_serie(["123457", "INT-48213", "SIN CODIGO"]), catalogo)
    assert not r["resuelto"].any()


@pytest.mark.parametrize("vacio", [None, "", "--", math.nan])
def test_c2_vacios_no_resuelven(catalogo, vacio):
    assert not capa_c2(_serie([vacio]), catalogo)["resuelto"].iloc[0]


def test_c2_clave_normalizada_ambigua(catalogo):
    r = capa_c2(_serie(["777-777"]), catalogo)
    assert not r["resuelto"].iloc[0]


def test_c2_ambiguedad_por_normalizacion():
    """Dos códigos distintos del catálogo que normalizan igual no se eligen al azar."""
    cat = pd.DataFrame({"codigo": ["012345", "12-345"], "procedimiento": ["A", "B"]})
    r = capa_c2(_serie(["12345"]), cat)
    assert not r["resuelto"].iloc[0]


def test_c2_conserva_indice(catalogo):
    r = capa_c2(_serie(["12-3456"], indice=[99]), catalogo)
    assert r.index.tolist() == [99]
    assert r.loc[99, "candidato_pos"] == 0
