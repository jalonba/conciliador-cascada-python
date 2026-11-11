import pandas as pd
import pytest

from conciliador import capas
from conciliador.cascada import (
    CAPAS,
    ESTADO_CONCILIADO,
    ESTADO_REVISAR,
    conciliar,
)
from datos.generar_sinteticos import generar


@pytest.fixture
def catalogo():
    return pd.DataFrame(
        {
            "codigo": ["100001", "012345", "47K815", "100004", "100005"],
            "procedimiento": [
                "RADIOGRAFÍA DE TÓRAX SIMPLE",
                "ECOGRAFÍA DE ABDOMEN",
                "RESONANCIA MAGNÉTICA DE RODILLA CON CONTRASTE",
                "SUTURA DE HERIDA EN CARA",
                "BIOPSIA DE TIROIDES GUIADA POR IMAGEN",
            ],
            "detalle": [
                "ESTUDIO RADIOLÓGICO CONVENCIONAL DE TÓRAX - BAJA COMPLEJIDAD",
                "ULTRASONIDO DIAGNÓSTICO DE ABDOMEN - BAJA COMPLEJIDAD",
                "ESTUDIO DE IMAGEN POR RESONANCIA DE RODILLA - ALTA COMPLEJIDAD",
                "CIERRE PRIMARIO DE LACERACIÓN EN CARA - MEDIANA COMPLEJIDAD",
                "TOMA DE MUESTRA HISTOLÓGICA DE TIROIDES - ALTA COMPLEJIDAD",
            ],
            "observacion": [
                "RX TX SIMP AMB",
                "ECO ABD HOSP",
                "RMN ROD C/CTE AMB",
                "SUT CAR URG",
                "",
            ],
            "tarifa": [10000, 20000, 30000, 40000, 50000],
        }
    )


@pytest.fixture
def facturado():
    return pd.DataFrame(
        {
            "codigo": ["100001", "12345", "47k8-15", "", "N/A", "", "INT-123", ""],
            "procedimiento": [
                "ECOGRAFIA DE ABDOMEN",  # contradice el código: manda C1
                "",
                "",
                "sutura de herida en cara",
                "VER DETALLE",
                "",
                "PAPELERIA ADMINISTRATIVA NOCTURNO",
                "",
            ],
            "detalle": [
                "",
                "",
                "",
                "",
                "toma de muestra histologica de tiroides alta complejidad",
                "",
                "",
                "",
            ],
            "observacion": ["", "", "", "", "", "rx tx simp amb", "", ""],
        },
        index=[10, 11, 12, 13, 14, 15, 16, 17],
    )


def test_cada_capa_resuelve_su_caso(catalogo, facturado):
    r = conciliar(facturado, catalogo).filas
    esperado = {
        10: ("C1", "100001"),
        11: ("C2", "012345"),
        12: ("C2", "47K815"),
        13: ("C3", "100004"),
        14: ("C4", "100005"),
        15: ("C5", "100001"),
    }
    for idx, (capa, candidato) in esperado.items():
        assert r.loc[idx, "estado"] == ESTADO_CONCILIADO, idx
        assert r.loc[idx, "capa"] == capa, idx
        assert r.loc[idx, "candidato"] == candidato, idx


def test_scores_por_capa(catalogo, facturado):
    r = conciliar(facturado, catalogo).filas
    assert r.loc[10, "score"] == 1.0
    assert r.loc[11, "score"] == 0.95
    assert r.loc[13, "score"] >= capas.UMBRAL_C3


def test_fila_resuelta_no_baja_a_la_siguiente(catalogo, facturado, monkeypatch):
    vistos: dict[str, list] = {}

    def espia(nombre, original):
        def envoltura(valores, *args, **kwargs):
            vistos[nombre] = list(valores.index)
            return original(valores, *args, **kwargs)

        return envoltura

    for nombre in ("capa_c2", "capa_c3", "capa_c4", "capa_c5"):
        monkeypatch.setattr(capas, nombre, espia(nombre, getattr(capas, nombre)))

    conciliar(facturado, catalogo)
    assert 10 not in vistos["capa_c2"]  # resuelta en C1
    assert not {10, 11, 12} & set(vistos["capa_c3"])  # resueltas en C1/C2
    assert 13 not in vistos["capa_c4"]
    assert 14 not in vistos["capa_c5"]


def test_bajo_umbral_sale_a_revision_con_mejor_candidato(catalogo, facturado):
    r = conciliar(facturado, catalogo).filas
    fila = r.loc[16]
    assert fila["estado"] == ESTADO_REVISAR
    assert pd.isna(fila["capa"])
    assert fila["candidato"] is not None
    assert fila["capa_candidato"] in {"C3", "C4", "C5"}
    assert fila["score"] < capas.UMBRAL_C3


def test_fila_sin_informacion_sale_a_revision_sin_candidato(catalogo, facturado):
    fila = conciliar(facturado, catalogo).filas.loc[17]
    assert fila["estado"] == ESTADO_REVISAR
    assert fila["candidato"] is None
    assert pd.isna(fila["score"])


def test_nunca_se_concilia_bajo_umbral(catalogo, facturado):
    r = conciliar(facturado, catalogo).filas
    umbrales = {"C1": 1.0, "C2": 0.95, "C3": 0.55, "C4": 0.55, "C5": 0.50}
    conciliadas = r[r["estado"] == ESTADO_CONCILIADO]
    for _, fila in conciliadas.iterrows():
        assert fila["score"] >= umbrales[fila["capa"]]
    assert r.loc[r["estado"] == ESTADO_REVISAR, "capa"].isna().all()


def test_salida_conserva_entrada_y_agrega_columnas(catalogo, facturado):
    original = facturado.copy()
    r = conciliar(facturado, catalogo).filas
    pd.testing.assert_frame_equal(facturado, original)  # no muta la entrada
    assert r.index.tolist() == facturado.index.tolist()
    for col in (
        "estado",
        "capa",
        "score",
        "candidato",
        "capa_candidato",
        "candidato_procedimiento",
    ):
        assert col in r.columns
    assert r.loc[10, "candidato_procedimiento"] == "RADIOGRAFÍA DE TÓRAX SIMPLE"


def test_resumen_por_capa(catalogo, facturado):
    res = conciliar(facturado, catalogo)
    resumen = res.resumen.set_index("resultado")
    assert list(resumen.index) == [*CAPAS, ESTADO_REVISAR, "TOTAL"]
    assert resumen.loc["TOTAL", "filas"] == len(facturado)
    assert resumen.loc[list(CAPAS) + [ESTADO_REVISAR], "filas"].sum() == len(facturado)
    assert resumen.loc["TOTAL", "porcentaje"] == pytest.approx(100.0)
    assert resumen.loc["C2", "filas"] == 2
    assert set(res.tiempos) >= set(CAPAS)


def test_columnas_de_texto_opcionales(catalogo):
    fac = pd.DataFrame({"codigo": ["100001", "x"]})
    r = conciliar(fac, catalogo).filas
    assert r["estado"].tolist() == [ESTADO_CONCILIADO, ESTADO_REVISAR]


def test_valida_columna_codigo(catalogo):
    with pytest.raises(ValueError, match="codigo"):
        conciliar(pd.DataFrame({"procedimiento": ["x"]}), catalogo)
    with pytest.raises(ValueError, match="codigo"):
        conciliar(pd.DataFrame({"codigo": ["1"]}), catalogo.drop(columns="codigo"))


def test_facturado_vacio(catalogo):
    res = conciliar(pd.DataFrame({"codigo": pd.Series([], dtype=object)}), catalogo)
    assert res.filas.empty
    assert res.resumen.set_index("resultado").loc["TOTAL", "filas"] == 0


# --------------------------------------------- propiedades sobre datos sintéticos


@pytest.fixture(scope="module")
def sintetico():
    cat, fac = generar(filas=4000, semilla=11, items_catalogo=1500)
    return fac, conciliar(fac, cat).filas


def test_c1_c2_sin_errores_en_sintetico(sintetico):
    fac, r = sintetico
    por_codigo = r[r["capa"].isin(["C1", "C2"])]
    assert len(por_codigo) > 0.6 * len(fac)
    assert (por_codigo["candidato"] == por_codigo["_codigo_verdadero"]).all()


def test_escenarios_de_codigo_se_resuelven_en_su_capa(sintetico):
    _, r = sintetico
    assert (r.loc[r["_escenario"] == "exacto", "capa"] == "C1").all()
    assert (r.loc[r["_escenario"] == "codigo_ruido", "capa"] == "C2").all()


def test_servicios_ajenos_no_se_concilian(sintetico):
    _, r = sintetico
    ajenos = r[r["_escenario"] == "sin_pareja_ajeno"]
    assert len(ajenos) > 0
    assert (ajenos["estado"] == ESTADO_REVISAR).all()
