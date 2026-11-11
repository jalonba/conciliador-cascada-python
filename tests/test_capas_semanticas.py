import math

import pandas as pd
import pytest

from conciliador.capas import (
    UMBRAL_C3,
    UMBRAL_C4,
    UMBRAL_C5,
    IndiceSemantico,
    capa_c3,
    capa_c4,
    capa_c5,
    capa_semantica,
    desempatar,
)


@pytest.fixture
def catalogo():
    return pd.DataFrame(
        {
            "codigo": ["100001", "100002", "100003", "10A004", "100005"],
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
            "observacion": ["RX TX SIMP AMB", "ECO ABD HOSP", "RMN ROD C/CTE AMB", "SUT CAR URG", ""],
        }
    )


def _serie(valores, indice=None):
    return pd.Series(valores, index=indice, dtype=object)


def test_umbrales_del_diseno():
    assert (UMBRAL_C3, UMBRAL_C4, UMBRAL_C5) == (0.55, 0.55, 0.50)


# ---------------------------------------------------------------------- C3


def test_c3_texto_identico(catalogo):
    r = capa_c3(_serie(["RADIOGRAFÍA DE TÓRAX SIMPLE"]), catalogo)
    assert r["resuelto"].iloc[0]
    assert r["candidato"].iloc[0] == "100001"
    assert r["score"].iloc[0] == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("radiografia de torax simple", "100001"),  # minúsculas y sin tildes
        ("RADIOGRAFIA DE TORAX SIMLPE X1", "100001"),  # error de digitación + texto extra
        ("ecografia abdomen", "100002"),
        ("PX RESONANCIA MAGNETICA RODILLA C/ CONTRASTE", "100003"),
        ("sutura herida en cara (URG)", "10A004"),
    ],
)
def test_c3_texto_con_ruido(catalogo, texto, esperado):
    r = capa_c3(_serie([texto]), catalogo)
    assert r["candidato"].iloc[0] == esperado
    assert r["resuelto"].iloc[0], r["score"].iloc[0]
    assert r["score"].iloc[0] >= UMBRAL_C3


def test_c3_bajo_umbral_conserva_candidato_pero_no_resuelve(catalogo):
    """Nunca se asigna en silencio: queda el mejor candidato para revisión humana."""
    r = capa_c3(_serie(["PAPELERIA ADMINISTRATIVA NOCTURNO"]), catalogo)
    assert not r["resuelto"].iloc[0]
    assert r["candidato"].iloc[0] is not None
    assert 0 <= r["score"].iloc[0] < UMBRAL_C3


@pytest.mark.parametrize("vacio", [None, "", "   ", "--", math.nan])
def test_c3_texto_vacio_sin_candidato(catalogo, vacio):
    r = capa_c3(_serie([vacio]), catalogo)
    assert not r["resuelto"].iloc[0]
    assert r["candidato"].iloc[0] is None
    assert math.isnan(r["score"].iloc[0])


def test_c3_conserva_indice(catalogo):
    r = capa_c3(_serie(["ecografia de abdomen", ""], indice=[7, 3]), catalogo)
    assert r.index.tolist() == [7, 3]
    assert r.loc[7, "candidato_pos"] == 1


def test_c3_entrada_vacia(catalogo):
    assert capa_c3(_serie([]), catalogo).empty


# ------------------------------------------------------------- C4 y C5


def test_c4_usa_columna_detalle(catalogo):
    r = capa_c4(_serie(["ultrasonido diagnostico de abdomen baja complejidad"]), catalogo)
    assert r["resuelto"].iloc[0]
    assert r["candidato"].iloc[0] == "100002"


def test_c4_no_mira_procedimiento(catalogo):
    # Este texto es idéntico a un «procedimiento», no a un «detalle».
    r = capa_c4(_serie(["SUTURA DE HERIDA EN CARA"]), catalogo)
    assert r["score"].iloc[0] < 0.99


def test_c5_usa_columna_observacion(catalogo):
    r = capa_c5(_serie(["rmn rod c/cte amb"]), catalogo)
    assert r["resuelto"].iloc[0]
    assert r["candidato"].iloc[0] == "100003"


def test_c5_ignora_items_sin_observacion(catalogo):
    """El ítem 100005 no tiene observación: no puede ser candidato de C5."""
    r = capa_c5(_serie(["BX TIR GUIADA"]), catalogo)
    assert r["candidato"].iloc[0] != "100005"


# ------------------------------------------------------------ umbral y lotes


def test_umbral_es_inclusivo(catalogo):
    textos = _serie(["ecografia abdomen"])
    score = capa_semantica(textos, catalogo, "procedimiento", umbral=0.0)["score"].iloc[0]
    justo = capa_semantica(textos, catalogo, "procedimiento", umbral=score)
    encima = capa_semantica(textos, catalogo, "procedimiento", umbral=score + 1e-6)
    assert justo["resuelto"].iloc[0]
    assert not encima["resuelto"].iloc[0]
    assert encima["candidato"].iloc[0] == justo["candidato"].iloc[0]


def test_resultado_independiente_del_tamano_de_lote(catalogo):
    textos = _serie(["ecografia abdomen", "rx torax", "sutura cara", "", "biopsia tiroides"])
    a = IndiceSemantico(catalogo["procedimiento"], tamano_lote=1).buscar(textos)
    b = IndiceSemantico(catalogo["procedimiento"], tamano_lote=1000).buscar(textos)
    pd.testing.assert_frame_equal(a, b)


def test_textos_duplicados_en_catalogo_son_ambiguos():
    cat = pd.DataFrame(
        {
            "codigo": ["1", "2", "3"],
            "procedimiento": ["CONSULTA GENERAL", "consulta general", "CURACION DE HERIDA"],
        }
    )
    r = capa_semantica(_serie(["CONSULTA GENERAL"]), cat, "procedimiento", umbral=0.5)
    assert not r["resuelto"].iloc[0]
    r2 = capa_semantica(_serie(["CURACION HERIDA"]), cat, "procedimiento", umbral=0.5)
    assert r2["resuelto"].iloc[0] and r2["candidato"].iloc[0] == "3"


def test_catalogo_sin_textos(catalogo):
    vacio = catalogo.assign(observacion="")
    r = capa_c5(_serie(["RX TX"]), vacio)
    assert not r["resuelto"].any()
    assert r["candidato"].iloc[0] is None


# --------------------------------------------------------------- desempate


def test_desempate_rapidfuzz_dentro_del_margen():
    candidatos = [(0, 0.80, "ECOGRAFIA DE CADERA BILATERAL"), (1, 0.79, "ECOGRAFIA DE CODO")]
    assert desempatar("ECOGRAFIA CODO", candidatos, margen=0.02) == 1


def test_desempate_no_actua_fuera_del_margen():
    candidatos = [(0, 0.80, "ECOGRAFIA DE CADERA BILATERAL"), (1, 0.70, "ECOGRAFIA DE CODO")]
    assert desempatar("ECOGRAFIA CODO", candidatos, margen=0.02) == 0


def test_desempate_determinista_en_empate_total():
    candidatos = [(5, 0.8, "ABC"), (2, 0.8, "ABC")]
    assert desempatar("ABC", candidatos, margen=0.02) == 2
