import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from conciliador.cascada import ESTADO_REVISAR, conciliar
from conciliador.cli import main
from conciliador.reportes import exportar

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalogo():
    return pd.DataFrame(
        {
            "codigo": ["012345", "100002", "100003"],
            "procedimiento": [
                "ECOGRAFÍA DE ABDOMEN",
                "SUTURA DE HERIDA EN CARA",
                "BIOPSIA DE MAMA",
            ],
            "detalle": ["", "", ""],
            "observacion": ["", "", ""],
            "tarifa": [1, 2, 3],
        }
    )


@pytest.fixture
def facturado():
    return pd.DataFrame(
        {
            "codigo": ["012345", "12345", "", "", ""],
            "procedimiento": [
                "",
                "",
                "sutura herida cara",
                '=HYPERLINK("http://ejemplo.invalid","clic")',
                "",
            ],
        }
    )


def _hoja(ruta: Path, nombre: str) -> pd.DataFrame:
    return pd.read_excel(ruta, sheet_name=nombre, dtype=str, keep_default_na=False)


def test_exportar_crea_los_dos_libros(tmp_path, catalogo, facturado):
    res = conciliar(facturado, catalogo)
    conciliado, auditoria = exportar(res, tmp_path)
    assert conciliado.name == "conciliado.xlsx"
    assert auditoria.name == "reporte_auditoria.xlsx"
    assert load_workbook(conciliado, read_only=True).sheetnames == ["conciliado"]
    assert load_workbook(auditoria, read_only=True).sheetnames == [
        "resumen",
        "revisar",
        "semanticas",
    ]


def test_conciliado_contiene_todas_las_filas(tmp_path, catalogo, facturado):
    res = conciliar(facturado, catalogo)
    conciliado, _ = exportar(res, tmp_path)
    hoja = _hoja(conciliado, "conciliado")
    assert len(hoja) == len(facturado)
    assert {"estado", "capa", "score", "candidato"} <= set(hoja.columns)
    assert hoja["codigo"].tolist()[:2] == ["012345", "12345"]  # ceros a la izquierda intactos


def test_resumen_con_porcentaje_por_capa(tmp_path, catalogo, facturado):
    res = conciliar(facturado, catalogo)
    _, auditoria = exportar(res, tmp_path)
    resumen = pd.read_excel(auditoria, sheet_name="resumen")
    fila = resumen.set_index("resultado")
    for capa in ("C1", "C2", "C3", "C4", "C5", ESTADO_REVISAR, "TOTAL"):
        assert capa in fila.index
    assert fila.loc["C1", "filas"] == 1
    assert fila.loc["C2", "filas"] == 1
    assert fila.loc["TOTAL", "porcentaje"] == pytest.approx(100.0)


def test_hoja_revisar_solo_trae_pendientes(tmp_path, catalogo, facturado):
    res = conciliar(facturado, catalogo)
    _, auditoria = exportar(res, tmp_path)
    revisar = _hoja(auditoria, "revisar")
    esperado = (res.filas["estado"] == ESTADO_REVISAR).sum()
    assert len(revisar) == esperado
    assert (revisar["estado"] == ESTADO_REVISAR).all()


def test_texto_con_formula_no_se_ejecuta(tmp_path, catalogo, facturado):
    """Un valor que empieza por «=» se guarda como texto, no como fórmula."""
    res = conciliar(facturado, catalogo)
    conciliado, _ = exportar(res, tmp_path)
    ws = load_workbook(conciliado).active
    celdas = [c for fila in ws.iter_rows() for c in fila if str(c.value).startswith("=")]
    assert celdas
    assert all(c.data_type == "s" for c in celdas)


# ------------------------------------------------------------------------- CLI


def test_cli_csv(tmp_path, catalogo, facturado, capsys):
    catalogo.to_csv(tmp_path / "cat.csv", index=False)
    facturado.to_csv(tmp_path / "fac.csv", index=False)
    salida = tmp_path / "salida"
    codigo = main(
        [
            "--facturado",
            str(tmp_path / "fac.csv"),
            "--catalogo",
            str(tmp_path / "cat.csv"),
            "--salida",
            str(salida),
        ]
    )
    assert codigo == 0
    assert (salida / "conciliado.xlsx").exists()
    assert (salida / "reporte_auditoria.xlsx").exists()
    # el CSV se lee como texto: «012345» no pierde el cero y resuelve en C1
    hoja = _hoja(salida / "conciliado.xlsx", "conciliado")
    assert hoja.loc[0, "capa"] == "C1"
    assert "C1" in capsys.readouterr().out


def test_cli_xlsx(tmp_path, catalogo, facturado):
    catalogo.to_excel(tmp_path / "cat.xlsx", index=False)
    facturado.to_excel(tmp_path / "fac.xlsx", index=False)
    codigo = main(
        [
            "--facturado",
            str(tmp_path / "fac.xlsx"),
            "--catalogo",
            str(tmp_path / "cat.xlsx"),
            "--salida",
            str(tmp_path / "out"),
        ]
    )
    assert codigo == 0
    assert (tmp_path / "out" / "conciliado.xlsx").exists()


def test_cli_archivo_inexistente(tmp_path, capsys):
    codigo = main(
        [
            "--facturado",
            str(tmp_path / "no.csv"),
            "--catalogo",
            str(tmp_path / "no2.csv"),
            "--salida",
            str(tmp_path),
        ]
    )
    assert codigo == 2
    assert "no existe" in capsys.readouterr().err


def test_python_m_conciliador(tmp_path, catalogo, facturado):
    catalogo.to_csv(tmp_path / "cat.csv", index=False)
    facturado.to_csv(tmp_path / "fac.csv", index=False)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "conciliador",
            "--facturado",
            str(tmp_path / "fac.csv"),
            "--catalogo",
            str(tmp_path / "cat.csv"),
            "--salida",
            str(tmp_path / "s"),
        ],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "s" / "reporte_auditoria.xlsx").exists()
