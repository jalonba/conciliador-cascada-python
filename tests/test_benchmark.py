import pandas as pd
import pytest

from benchmark.correr import correr, metricas, tabla_markdown
from conciliador.cascada import ESTADO_CONCILIADO, ESTADO_REVISAR


@pytest.fixture
def filas():
    c, r = ESTADO_CONCILIADO, ESTADO_REVISAR
    return pd.DataFrame(
        {
            "estado": [c, c, c, c, r, c, r],
            "capa": ["C1", "C2", "C3", "C3", None, "C3", None],
            "candidato": ["A", "B", "C", "X", "Y", "Z", None],
            "_escenario": [
                "exacto",
                "codigo_ruido",
                "texto_procedimiento",
                "texto_procedimiento",
                "degradado",
                "sin_pareja_vecino",
                "sin_pareja_ajeno",
            ],
            "_codigo_verdadero": ["A", "B", "C", "D", "E", "", ""],
        }
    )


def test_metricas_por_capa(filas):
    m = metricas(filas)
    capas = m["por_capa"].set_index("resultado")
    assert capas.loc["C1", "filas"] == 1
    assert capas.loc["C3", "filas"] == 3
    # C3: una correcta (C), una con pareja equivocada (X≠D) y un falso positivo sin pareja
    assert capas.loc["C3", "precision"] == pytest.approx(100 / 3)
    assert capas.loc["REVISAR_SCORE_BAJO", "filas"] == 2
    assert capas.loc["TOTAL", "porcentaje"] == pytest.approx(100.0)


def test_metricas_globales(filas):
    g = metricas(filas)["global"]
    assert g["filas"] == 7
    assert g["resuelto_pct"] == pytest.approx(500 / 7)
    assert g["revisar_pct"] == pytest.approx(200 / 7)
    assert g["precision_resueltas_pct"] == pytest.approx(60.0)  # 3 de 5
    assert g["sin_pareja"] == 2
    assert g["sin_pareja_conciliadas"] == 1  # el vecino se concilió (falso positivo)


def test_metricas_por_escenario(filas):
    esc = metricas(filas)["por_escenario"].set_index("escenario")
    assert esc.loc["texto_procedimiento", "filas"] == 2
    assert esc.loc["texto_procedimiento", "conciliado_pct"] == pytest.approx(100.0)
    assert esc.loc["texto_procedimiento", "correcto_pct"] == pytest.approx(50.0)
    assert esc.loc["sin_pareja_ajeno", "conciliado_pct"] == 0.0


def test_correr_extremo_a_extremo(tmp_path):
    md = tmp_path / "resultados.md"
    informe = correr(filas=3000, semilla=5, items_catalogo=800, salida_md=md, excel_dir=None)
    texto = md.read_text(encoding="utf-8")
    assert "| C1 |" in texto and "| REVISAR_SCORE_BAJO |" in texto
    assert "3,000" in texto or "3.000" in texto
    assert informe["global"]["filas"] == 3000
    assert informe["tiempos"]["cascada"] > 0


def test_tabla_markdown_sin_maquillar(filas):
    m = metricas(filas)
    m["tiempos"] = {"generacion": 0.1, "cascada": 1.23456, "C1": 0.1}
    texto = tabla_markdown(m, filas=7, semilla=1, items_catalogo=5)
    assert "1.23" in texto
