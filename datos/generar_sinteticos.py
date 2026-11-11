"""Generador de datos 100 % sintéticos para probar y medir el conciliador.

Produce dos tablas:

* ``catalogo``: ítems inventados con código de 6 caracteres (algunos
  alfanuméricos), ``procedimiento``, ``detalle``, ``observacion`` y ``tarifa``.
* ``facturado``: filas que referencian el catálogo con ruido controlado, más un
  porcentaje de filas **sin pareja real** para comprobar que la cascada no
  inventa coincidencias.

Los códigos se generan al azar con la semilla dada; no se copian de ningún
tarifario real. Las columnas ``_escenario`` y ``_codigo_verdadero`` del
facturado son la «verdad de terreno» que usa el benchmark; el conciliador las
ignora.

Uso::

    python -m datos.generar_sinteticos --filas 250000 --semilla 42 --salida datos/sinteticos
"""

from __future__ import annotations

import argparse
import itertools
import random
import string
import sys
from pathlib import Path

import pandas as pd

from conciliador.normalizar import normalizar_codigo, quitar_tildes

COLUMNAS_CATALOGO = ["codigo", "procedimiento", "detalle", "observacion", "tarifa"]
COLUMNAS_FACTURADO = [
    "id_fila",
    "codigo",
    "procedimiento",
    "detalle",
    "observacion",
    "cantidad",
    "valor",
    "_escenario",
    "_codigo_verdadero",
]

# Escenario → peso. Los pesos suman 1.
PESOS_ESCENARIOS: dict[str, float] = {
    "exacto": 0.42,  # código idéntico → debería resolver C1
    "codigo_ruido": 0.24,  # código con ruido normalizable → C2
    "texto_procedimiento": 0.16,  # sin código válido; procedimiento con ruido → C3
    "texto_detalle": 0.06,  # procedimiento inútil; detalle con ruido → C4
    "texto_observacion": 0.04,  # solo la observación sirve → C5
    "degradado": 0.02,  # todo muy dañado → probablemente REVISAR
    "sin_pareja_ajeno": 0.03,  # servicio que no existe en el catálogo
    "sin_pareja_vecino": 0.03,  # combinación plausible que el catálogo no tiene
}
ESCENARIOS = list(PESOS_ESCENARIOS)

# (procedimiento base, redacción alternativa para «detalle», abreviatura para «observacion»)
BASES: list[tuple[str, str, str]] = [
    ("RADIOGRAFÍA DE", "ESTUDIO RADIOLÓGICO CONVENCIONAL DE", "RX"),
    ("ECOGRAFÍA DE", "ULTRASONIDO DIAGNÓSTICO DE", "ECO"),
    ("ECOGRAFÍA DOPPLER DE", "ESTUDIO VASCULAR CON ULTRASONIDO DE", "DOP"),
    ("TOMOGRAFÍA COMPUTADA DE", "ESTUDIO TOMOGRÁFICO MULTICORTE DE", "TAC"),
    ("RESONANCIA MAGNÉTICA DE", "ESTUDIO DE IMAGEN POR RESONANCIA DE", "RMN"),
    ("GAMMAGRAFÍA DE", "ESTUDIO DE MEDICINA NUCLEAR DE", "GAM"),
    ("BIOPSIA DE", "TOMA DE MUESTRA HISTOLÓGICA DE", "BX"),
    ("BIOPSIA POR ASPIRACIÓN DE", "PUNCIÓN CON AGUJA FINA PARA CITOLOGÍA DE", "BACAF"),
    ("DRENAJE DE COLECCIÓN EN", "EVACUACIÓN DE ABSCESO O HEMATOMA EN", "DREN"),
    ("RESECCIÓN DE LESIÓN EN", "EXTIRPACIÓN QUIRÚRGICA DE MASA EN", "RESEC"),
    ("SUTURA DE HERIDA EN", "CIERRE PRIMARIO DE LACERACIÓN EN", "SUT"),
    ("CURACIÓN DE HERIDA EN", "LIMPIEZA Y CUBRIMIENTO DE LESIÓN EN", "CUR"),
    ("INFILTRACIÓN DE", "APLICACIÓN DE MEDICAMENTO INTRAARTICULAR O LOCAL EN", "INF"),
    ("ARTROSCOPIA DE", "EXPLORACIÓN ARTICULAR ENDOSCÓPICA DE", "ARTX"),
    ("ANGIOGRAFÍA DE", "ESTUDIO CONTRASTADO DE VASOS DE", "ANGIO"),
    ("REDUCCIÓN CERRADA DE FRACTURA EN", "ALINEACIÓN MANUAL DE FRACTURA SIN INCISIÓN EN", "RCF"),
    ("OSTEOSÍNTESIS DE", "FIJACIÓN INTERNA CON MATERIAL DE", "OTS"),
    ("INJERTO DE PIEL EN", "COBERTURA CUTÁNEA CON AUTOINJERTO EN", "INJ"),
    ("RECONSTRUCCIÓN DE", "REPARACIÓN ANATÓMICA COMPLEJA DE", "RECON"),
    ("EXPLORACIÓN QUIRÚRGICA DE", "REVISIÓN OPERATORIA DIAGNÓSTICA DE", "EXPL"),
    ("LAVADO QUIRÚRGICO DE", "DESBRIDAMIENTO E IRRIGACIÓN DE", "LAV"),
    ("INMOVILIZACIÓN DE", "COLOCACIÓN DE FÉRULA O YESO EN", "INMOV"),
    ("PUNCIÓN DIAGNÓSTICA DE", "ASPIRACIÓN DE LÍQUIDO PARA ESTUDIO DE", "PUN"),
    ("LIBERACIÓN DE ADHERENCIAS EN", "LISIS DE BRIDAS EN", "LIB"),
    ("TERAPIA FÍSICA INTEGRAL DE", "SESIÓN DE REHABILITACIÓN MOTORA DE", "TF"),
    ("ELECTROMIOGRAFÍA DE", "ESTUDIO NEUROFISIOLÓGICO DE", "EMG"),
    ("MAMOGRAFÍA DE", "ESTUDIO RADIOLÓGICO MAMARIO DE", "MMG"),
    ("ESCLEROTERAPIA DE", "INYECCIÓN ESCLEROSANTE EN VARICES DE", "ESCL"),
    ("ABLACIÓN POR RADIOFRECUENCIA DE", "DESTRUCCIÓN TÉRMICA DE TEJIDO EN", "ARF"),
    ("ENDOSCOPIA DIAGNÓSTICA DE", "VISUALIZACIÓN ENDOSCÓPICA DE", "ENDO"),
    ("FISTULECTOMÍA DE", "RESECCIÓN DE TRAYECTO FISTULOSO EN", "FIST"),
    ("PLASTIA DE", "REMODELACIÓN QUIRÚRGICA DE", "PLAS"),
    ("RETIRO DE MATERIAL DE OSTEOSÍNTESIS DE", "EXTRACCIÓN DE IMPLANTE ORTOPÉDICO DE", "RMO"),
    ("BLOQUEO NERVIOSO DE", "ANESTESIA REGIONAL CONDUCTIVA DE", "BLQ"),
]

# (sitio anatómico, abreviatura)
SITIOS: list[tuple[str, str]] = [
    ("TÓRAX", "TX"),
    ("ABDOMEN", "ABD"),
    ("PELVIS", "PELV"),
    ("CRÁNEO", "CRAN"),
    ("COLUMNA CERVICAL", "COL CERV"),
    ("COLUMNA DORSAL", "COL DORS"),
    ("COLUMNA LUMBAR", "COL LUMB"),
    ("RODILLA", "ROD"),
    ("HOMBRO", "HOMB"),
    ("CODO", "COD"),
    ("MUÑECA", "MUN"),
    ("MANO", "MAN"),
    ("CADERA", "CAD"),
    ("TOBILLO", "TOB"),
    ("PIE", "PIE"),
    ("CUELLO", "CUEL"),
    ("MAMA", "MAM"),
    ("TIROIDES", "TIR"),
    ("HÍGADO", "HIG"),
    ("RIÑÓN", "RIN"),
    ("VEJIGA", "VEJ"),
    ("PRÓSTATA", "PROST"),
    ("ÚTERO", "UT"),
    ("OVARIO", "OV"),
    ("CORAZÓN", "COR"),
    ("MIEMBRO SUPERIOR", "MMSS"),
    ("MIEMBRO INFERIOR", "MMII"),
    ("ANTEBRAZO", "ANTEB"),
    ("BRAZO", "BRZ"),
    ("MUSLO", "MUS"),
    ("PIERNA", "PIER"),
    ("CARA", "CAR"),
    ("NARIZ", "NAR"),
    ("OÍDO", "OID"),
    ("ÓRBITA", "ORB"),
    ("SENOS PARANASALES", "SPN"),
    ("ESCROTO", "ESCR"),
    ("REGIÓN INGUINAL", "ING"),
    ("PARED ABDOMINAL", "PAR ABD"),
    ("REGIÓN GLÚTEA", "GLUT"),
]

# (calificador, abreviatura)
CALIFICADORES: list[tuple[str, str]] = [
    ("", ""),
    ("SIMPLE", "SIMP"),
    ("CON CONTRASTE", "C/CTE"),
    ("BILATERAL", "BILAT"),
    ("UNILATERAL", "UNILAT"),
    ("POR VÍA ABIERTA", "ABIERTA"),
    ("POR VÍA ENDOSCÓPICA", "ENDOSC"),
    ("GUIADA POR IMAGEN", "GUIADA"),
]

COMPLEJIDADES = ["BAJA COMPLEJIDAD", "MEDIANA COMPLEJIDAD", "ALTA COMPLEJIDAD"]
AMBITOS = ["AMB", "HOSP", "URG"]

# Servicios que no existen en el catálogo (para filas sin pareja «ajenas»).
AJENOS_BASE = [
    "SERVICIO DE TRANSPORTE ASISTENCIAL",
    "ALIMENTACIÓN DE ACOMPAÑANTE",
    "COPIA DE HISTORIA CLÍNICA",
    "CERTIFICADO DE ASISTENCIA",
    "KIT DE ASEO PERSONAL",
    "SERVICIO DE PARQUEADERO",
    "LAVANDERÍA DE PRENDAS PERSONALES",
    "SERVICIO DE TELEFONÍA",
    "CAMA ADICIONAL PARA ACOMPAÑANTE",
    "PAPELERÍA ADMINISTRATIVA",
]
AJENOS_MODIFICADOR = ["DIURNO", "NOCTURNO", "FIN DE SEMANA", "URBANO", "RURAL", "POR EVENTO"]

ABREVIATURAS: list[tuple[str, str]] = [
    ("RADIOGRAFÍA", "RX"),
    ("ECOGRAFÍA", "ECO"),
    ("TOMOGRAFÍA COMPUTADA", "TAC"),
    ("RESONANCIA MAGNÉTICA", "RMN"),
    ("QUIRÚRGICO", "QX"),
    ("QUIRÚRGICA", "QX"),
    ("COLUMNA", "COL"),
    ("CERVICAL", "CERV"),
    ("LUMBAR", "LUMB"),
    ("BILATERAL", "BILAT"),
    ("CONTRASTE", "CTE"),
    ("FRACTURA", "FX"),
    ("TERAPIA", "TX"),
    ("MIEMBRO", "MBRO"),
    ("SUPERIOR", "SUP"),
    ("INFERIOR", "INF"),
    ("DIAGNÓSTICA", "DX"),
    ("RECONSTRUCCIÓN", "RECONST"),
    ("REGIÓN", "REG"),
]

PREFIJOS_EXTRA = ["PX ", "PROC ", "SERV ", "* "]
SUFIJOS_EXTRA = [" X1", " AMB", " SEGÚN ORDEN MÉDICA", " CX PROGRAMADA", " (URG)", " PTE REMITIDO"]
MARCADORES_VACIOS = ["", "PROCEDIMIENTO", "SERVICIO", "VER DETALLE", "OTROS", "PAQUETE", "N/A"]
CODIGOS_INVALIDOS = ["", "SIN CODIGO", "N/A", "S/C", "PEND"]

_LETRAS_CODIGO = [c for c in string.ascii_uppercase if c not in "IO"]
_LETRAS_RUIDO = string.ascii_uppercase


# --------------------------------------------------------------------- códigos


def _codigo_aleatorio(rng: random.Random, prob_alfanumerico: float) -> str:
    digitos = [rng.choice(string.digits) for _ in range(6)]
    if rng.random() < prob_alfanumerico:
        digitos[rng.randint(1, 4)] = rng.choice(_LETRAS_CODIGO)
    return "".join(digitos)


def _generar_codigos(rng: random.Random, n: int, prob_alfanumerico: float = 0.15) -> list[str]:
    vistos: set[str] = set()
    codigos: list[str] = []
    while len(codigos) < n:
        codigo = _codigo_aleatorio(rng, prob_alfanumerico)
        if codigo in vistos or set(codigo) == {"0"}:
            continue
        vistos.add(codigo)
        codigos.append(codigo)
    return codigos


def _ruido_codigo(rng: random.Random, codigo: str) -> str:
    """Devuelve una variante distinta de ``codigo`` que normaliza igual."""
    operaciones = ["guion", "puntos", "espacio", "mas_ceros"]
    if codigo.startswith("0"):
        operaciones += ["sin_ceros", "sin_ceros"]
    if any(c.isalpha() for c in codigo):
        operaciones += ["minusculas", "minusculas"]
    while True:
        resultado = codigo
        for op in rng.sample(operaciones, k=rng.choice([1, 1, 2])):
            if op == "guion":
                p = rng.randint(1, len(resultado) - 1)
                resultado = resultado[:p] + "-" + resultado[p:]
            elif op == "puntos":
                resultado = ".".join(resultado[i : i + 2] for i in range(0, len(resultado), 2))
            elif op == "espacio":
                p = rng.randint(1, len(resultado) - 1)
                resultado = resultado[:p] + " " + resultado[p:]
            elif op == "mas_ceros":
                resultado = "0" * rng.randint(1, 2) + resultado
            elif op == "sin_ceros":
                resultado = resultado.lstrip("0")
            elif op == "minusculas":
                resultado = resultado.lower()
        if resultado != codigo and normalizar_codigo(resultado) == normalizar_codigo(codigo):
            return resultado


# ---------------------------------------------------------------------- textos


def _errores_digitacion(rng: random.Random, texto: str, n: int) -> str:
    chars = list(texto)
    for _ in range(n):
        posiciones = [i for i, c in enumerate(chars) if c.isalpha()]
        if len(posiciones) < 2:
            break
        i = rng.choice(posiciones)
        op = rng.choice(["cambio", "borrado", "duplicado", "transposicion"])
        if op == "cambio":
            chars[i] = rng.choice(_LETRAS_RUIDO)
        elif op == "borrado":
            del chars[i]
        elif op == "duplicado":
            chars.insert(i, chars[i])
        elif op == "transposicion" and i + 1 < len(chars):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def _abreviar(rng: random.Random, texto: str) -> str:
    for largo, corto in ABREVIATURAS:
        if largo in texto and rng.random() < 0.7:
            texto = texto.replace(largo, corto)
    if rng.random() < 0.3:
        texto = texto.replace(" DE ", " ")
    return texto


def _ruido_texto(rng: random.Random, texto: str, intensidad: str) -> str:
    """Aplica ruido ``leve``, ``medio`` o ``fuerte`` a un texto del catálogo."""
    if not texto:
        return texto
    if rng.random() < 0.6:
        texto = quitar_tildes(texto)
    if intensidad in ("medio", "fuerte"):
        if rng.random() < 0.5:
            texto = _abreviar(rng, texto)
        n_errores = rng.choice([0, 1, 1, 2]) if intensidad == "medio" else rng.randint(3, 6)
        texto = _errores_digitacion(rng, texto, n_errores)
        if rng.random() < 0.35:
            texto = rng.choice(PREFIJOS_EXTRA) + texto
        if rng.random() < 0.35:
            texto = texto + rng.choice(SUFIJOS_EXTRA)
    if intensidad == "fuerte":
        palabras = texto.split()
        conservar = max(1, int(len(palabras) * rng.uniform(0.4, 0.6)))
        texto = " ".join(palabras[:conservar])
    if rng.random() < 0.25:
        texto = texto.lower()
    elif rng.random() < 0.1:
        texto = texto.title()
    return texto


# -------------------------------------------------------------------- catálogo


def _textos_item(base_idx: int, sitio_idx: int, calif_idx: int, complejidad: str, ambito: str):
    base, base_detalle, base_abrev = BASES[base_idx]
    sitio, sitio_abrev = SITIOS[sitio_idx]
    calif, calif_abrev = CALIFICADORES[calif_idx]
    procedimiento = " ".join(p for p in (base, sitio, calif) if p)
    detalle = " ".join(p for p in (base_detalle, sitio, calif, "-", complejidad) if p)
    observacion = " ".join(p for p in (base_abrev, sitio_abrev, calif_abrev, ambito) if p)
    return procedimiento, detalle, observacion


def _combinaciones(rng: random.Random) -> list[tuple[int, int, int]]:
    combos = list(
        itertools.product(range(len(BASES)), range(len(SITIOS)), range(len(CALIFICADORES)))
    )
    rng.shuffle(combos)
    return combos


def _catalogo_y_vecinos(items: int, semilla: int):
    rng = random.Random(f"catalogo-{semilla}")
    combos = _combinaciones(rng)
    if items > len(combos):
        raise ValueError(f"items_catalogo máximo: {len(combos)}")
    codigos = _generar_codigos(rng, items)
    filas = []
    for codigo, (b, s, c) in zip(codigos, combos[:items], strict=True):
        procedimiento, detalle, observacion = _textos_item(
            b, s, c, rng.choice(COMPLEJIDADES), rng.choice(AMBITOS)
        )
        tarifa = rng.randint(200, 20000) * 100
        filas.append((codigo, procedimiento, detalle, observacion, tarifa))
    catalogo = pd.DataFrame(filas, columns=COLUMNAS_CATALOGO)
    return catalogo, combos[items:]


def generar_catalogo(items: int = 6000, semilla: int = 42) -> pd.DataFrame:
    """Catálogo/tarifario inventado con ``items`` filas."""
    return _catalogo_y_vecinos(items, semilla)[0]


# ------------------------------------------------------------------- facturado


def generar(
    filas: int = 250_000, semilla: int = 42, items_catalogo: int = 6000
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve ``(catalogo, facturado)`` deterministas para la semilla dada."""
    catalogo, combos_libres = _catalogo_y_vecinos(items_catalogo, semilla)
    rng = random.Random(f"facturado-{semilla}")

    codigos_cat = catalogo["codigo"].tolist()
    normalizados_cat = set(map(normalizar_codigo, codigos_cat))
    registros = catalogo.to_dict("records")

    def codigo_inexistente() -> str:
        while True:
            codigo = _codigo_aleatorio(rng, 0.15)
            if normalizar_codigo(codigo) not in normalizados_cat:
                return codigo

    def codigo_invalido() -> str:
        if rng.random() < 0.3:
            return f"INT-{rng.randint(10000, 99999)}"
        return rng.choice(CODIGOS_INVALIDOS)

    escenarios = rng.choices(ESCENARIOS, weights=list(PESOS_ESCENARIOS.values()), k=filas)
    salida = []
    for i, escenario in enumerate(escenarios, start=1):
        cantidad = rng.choice([1, 1, 1, 1, 2, 3])
        if escenario.startswith("sin_pareja"):
            if escenario == "sin_pareja_ajeno":
                proc = f"{rng.choice(AJENOS_BASE)} {rng.choice(AJENOS_MODIFICADOR)}"
                det, obs = proc, ""
            else:
                b, s, c = rng.choice(combos_libres)
                proc, det, obs = _textos_item(
                    b, s, c, rng.choice(COMPLEJIDADES), rng.choice(AMBITOS)
                )
            codigo = codigo_inexistente() if rng.random() < 0.7 else codigo_invalido()
            fila = (
                codigo,
                _ruido_texto(rng, proc, "leve"),
                _ruido_texto(rng, det, "leve") if rng.random() < 0.6 else "",
                _ruido_texto(rng, obs, "leve") if rng.random() < 0.4 else "",
                cantidad,
                rng.randint(200, 20000) * 100 * cantidad,
                escenario,
                "",
            )
            salida.append((i, *fila))
            continue

        item = registros[rng.randrange(len(registros))]
        proc, det, obs = item["procedimiento"], item["detalle"], item["observacion"]
        if escenario == "exacto":
            codigo = item["codigo"]
            proc = _ruido_texto(rng, proc, "leve")
            det = _ruido_texto(rng, det, "leve") if rng.random() < 0.5 else ""
            obs = _ruido_texto(rng, obs, "leve") if rng.random() < 0.3 else ""
        elif escenario == "codigo_ruido":
            codigo = _ruido_codigo(rng, item["codigo"])
            proc = _ruido_texto(rng, proc, "leve")
            det = _ruido_texto(rng, det, "leve") if rng.random() < 0.5 else ""
            obs = _ruido_texto(rng, obs, "leve") if rng.random() < 0.3 else ""
        elif escenario == "texto_procedimiento":
            codigo = codigo_invalido()
            proc = _ruido_texto(rng, proc, "medio")
            det = _ruido_texto(rng, det, "medio") if rng.random() < 0.4 else ""
            obs = _ruido_texto(rng, obs, "medio") if rng.random() < 0.3 else ""
        elif escenario == "texto_detalle":
            codigo = codigo_invalido()
            proc = rng.choice(MARCADORES_VACIOS)
            det = _ruido_texto(rng, det, "medio")
            obs = _ruido_texto(rng, obs, "medio") if rng.random() < 0.3 else ""
        elif escenario == "texto_observacion":
            codigo = codigo_invalido()
            proc = rng.choice(MARCADORES_VACIOS)
            det = rng.choice(MARCADORES_VACIOS)
            obs = _ruido_texto(rng, obs, "leve")
        else:  # degradado
            codigo = codigo_invalido()
            proc = _ruido_texto(rng, proc, "fuerte")
            det = _ruido_texto(rng, det, "fuerte") if rng.random() < 0.5 else ""
            obs = ""
        salida.append(
            (
                i,
                codigo,
                proc,
                det,
                obs,
                cantidad,
                item["tarifa"] * cantidad,
                escenario,
                item["codigo"],
            )
        )

    facturado = pd.DataFrame(salida, columns=COLUMNAS_FACTURADO)
    return catalogo, facturado


# ------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera catálogo y facturado sintéticos.")
    parser.add_argument("--filas", type=int, default=250_000)
    parser.add_argument("--semilla", type=int, default=42)
    parser.add_argument("--items-catalogo", type=int, default=6000)
    parser.add_argument("--salida", type=Path, default=Path("datos/sinteticos"))
    args = parser.parse_args(argv)

    catalogo, facturado = generar(args.filas, args.semilla, args.items_catalogo)
    args.salida.mkdir(parents=True, exist_ok=True)
    catalogo.to_csv(args.salida / "catalogo.csv", index=False)
    facturado.to_csv(args.salida / "facturado.csv", index=False)
    print(
        f"catálogo: {len(catalogo):,} ítems · facturado: {len(facturado):,} filas "
        f"→ {args.salida}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
