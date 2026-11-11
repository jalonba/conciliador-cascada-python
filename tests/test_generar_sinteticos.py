import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from conciliador.normalizar import normalizar_codigo
from datos.generar_sinteticos import (
    COLUMNAS_CATALOGO,
    COLUMNAS_FACTURADO,
    ESCENARIOS,
    generar,
    generar_catalogo,
)

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def datos():
    return generar(filas=6000, semilla=7, items_catalogo=800)


# ------------------------------------------------------------ determinismo


def test_misma_semilla_mismo_resultado():
    cat1, fac1 = generar(filas=1500, semilla=42, items_catalogo=300)
    cat2, fac2 = generar(filas=1500, semilla=42, items_catalogo=300)
    pd.testing.assert_frame_equal(cat1, cat2)
    pd.testing.assert_frame_equal(fac1, fac2)


def test_semilla_distinta_resultado_distinto():
    _, fac1 = generar(filas=1500, semilla=1, items_catalogo=300)
    _, fac2 = generar(filas=1500, semilla=2, items_catalogo=300)
    assert not fac1.equals(fac2)


def _huella_en_subproceso(tmp_path: Path, hashseed: str) -> str:
    salida = tmp_path / f"h{hashseed}"
    entorno = {**os.environ, "PYTHONHASHSEED": hashseed}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "datos.generar_sinteticos",
            "--filas",
            "1200",
            "--semilla",
            "42",
            "--items-catalogo",
            "300",
            "--salida",
            str(salida),
        ],
        check=True,
        cwd=RAIZ,
        env=entorno,
        capture_output=True,
    )
    h = hashlib.sha256()
    for nombre in ("catalogo.csv", "facturado.csv"):
        h.update((salida / nombre).read_bytes())
    return h.hexdigest()


def test_determinista_entre_procesos_con_hash_distinto(tmp_path):
    """El orden de iteración de sets de str cambia con PYTHONHASHSEED; la salida no debe."""
    assert _huella_en_subproceso(tmp_path, "1") == _huella_en_subproceso(tmp_path, "999")


# ---------------------------------------------------------------- catálogo


def test_catalogo_columnas_y_tamano():
    cat = generar_catalogo(items=500, semilla=3)
    assert list(cat.columns) == COLUMNAS_CATALOGO
    assert len(cat) == 500


def test_catalogo_codigos_formato_y_unicidad(datos):
    cat, _ = datos
    codigos = cat["codigo"]
    assert codigos.str.fullmatch(r"[0-9A-Z]{6}").all()
    assert codigos.is_unique
    assert codigos.map(normalizar_codigo).is_unique


def test_catalogo_incluye_codigos_alfanumericos(datos):
    cat, _ = datos
    alfanumericos = cat["codigo"].str.contains(r"[A-Z]")
    assert 0.05 < alfanumericos.mean() < 0.40


def test_catalogo_incluye_codigos_con_cero_inicial(datos):
    cat, _ = datos
    assert cat["codigo"].str.startswith("0").any()


def test_catalogo_procedimiento_unico(datos):
    cat, _ = datos
    assert cat["procedimiento"].is_unique
    assert cat["procedimiento"].str.len().gt(0).all()


# --------------------------------------------------------------- facturado


def test_facturado_columnas_y_tamano(datos):
    _, fac = datos
    assert list(fac.columns) == COLUMNAS_FACTURADO
    assert len(fac) == 6000


def test_facturado_escenarios_conocidos(datos):
    _, fac = datos
    assert set(fac["_escenario"]).issubset(set(ESCENARIOS))
    # con 6000 filas deben aparecer todos los escenarios
    assert set(fac["_escenario"]) == set(ESCENARIOS)


def test_filas_sin_pareja_no_tienen_codigo_del_catalogo(datos):
    cat, fac = datos
    sin_pareja = fac[fac["_escenario"].str.startswith("sin_pareja")]
    assert 0.03 < len(sin_pareja) / len(fac) < 0.10
    assert (sin_pareja["_codigo_verdadero"] == "").all()
    codigos_cat = set(cat["codigo"].map(normalizar_codigo))
    assert not sin_pareja["codigo"].map(normalizar_codigo).isin(codigos_cat).any()


def test_filas_sin_pareja_no_copian_texto_del_catalogo(datos):
    """Ni las ajenas ni las «vecinas» (combinación no usada) existen en el catálogo."""
    cat, fac = datos
    sin_pareja = fac[fac["_escenario"].str.startswith("sin_pareja")]
    assert not sin_pareja["procedimiento"].isin(set(cat["procedimiento"])).any()


def test_filas_con_pareja_apuntan_al_catalogo(datos):
    cat, fac = datos
    con_pareja = fac[~fac["_escenario"].str.startswith("sin_pareja")]
    assert con_pareja["_codigo_verdadero"].isin(set(cat["codigo"])).all()


def test_escenario_exacto_conserva_codigo(datos):
    _, fac = datos
    exactos = fac[fac["_escenario"] == "exacto"]
    assert (exactos["codigo"] == exactos["_codigo_verdadero"]).all()


def test_escenario_codigo_ruido_difiere_pero_normaliza_igual(datos):
    _, fac = datos
    ruido = fac[fac["_escenario"] == "codigo_ruido"]
    assert (ruido["codigo"] != ruido["_codigo_verdadero"]).all()
    assert (
        ruido["codigo"].map(normalizar_codigo) == ruido["_codigo_verdadero"].map(normalizar_codigo)
    ).all()


def test_ruido_de_codigo_variado(datos):
    _, fac = datos
    ruido = fac.loc[fac["_escenario"] == "codigo_ruido", "codigo"]
    assert ruido.str.contains("-").any()  # guiones
    assert ruido.str.contains(r"[a-z]").any()  # minúsculas
    assert ruido.str.len().lt(6).any()  # ceros a la izquierda perdidos


def test_escenarios_textuales_no_traen_codigo_valido(datos):
    cat, fac = datos
    textuales = fac[fac["_escenario"].str.startswith("texto_") | (fac["_escenario"] == "degradado")]
    codigos_cat = set(cat["codigo"].map(normalizar_codigo))
    assert not textuales["codigo"].map(normalizar_codigo).isin(codigos_cat).any()


def test_ruido_textual_presente(datos):
    cat, fac = datos
    texto = fac.loc[fac["_escenario"] == "texto_procedimiento", "procedimiento"]
    # parte del texto llega sin tildes y no es idéntico al catálogo
    assert not texto.str.contains("[ÁÉÍÓÚ]").all()
    assert not texto.isin(set(cat["procedimiento"])).all()


def test_escenario_detalle_sin_procedimiento_util(datos):
    _, fac = datos
    filas = fac[fac["_escenario"] == "texto_detalle"]
    assert filas["detalle"].str.len().gt(0).all()
    assert filas["procedimiento"].str.len().lt(25).all()
