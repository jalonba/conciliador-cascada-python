# Resultados del benchmark sintético

Generado con `python -m benchmark.correr --filas 250000 --semilla 42 --items-catalogo 6000`.

- Filas facturadas: **250,000** · ítems de catálogo: **6,000**
- Entorno: Python 3.12.3 · pandas 3.1.1 · scikit-learn 1.9.1 · 8 núcleos lógicos · Linux

## Resolución por capa

| Capa | Umbral | Filas | % del total | Precisión |
|---|---|---:|---:|---:|
| C1 | 1.00 | 105,156 | 42.1 % | 100.0 % |
| C2 | 0.95 | 59,884 | 24.0 % | 100.0 % |
| C3 | 0.55 | 51,479 | 20.6 % | 74.3 % |
| C4 | 0.55 | 15,440 | 6.2 % | 95.5 % |
| C5 | 0.50 | 10,072 | 4.0 % | 100.0 % |
| REVISAR_SCORE_BAJO |  | 7,969 | 3.2 % | — |
| TOTAL |  | 250,000 | 100.0 % | 94.2 % |

Precisión = filas cuyo candidato coincide con el código verdadero ÷ filas resueltas por la capa (las filas sin pareja que se concilian cuentan como error).

## Resumen

- Resuelto automáticamente: **96.8 %**
- A revisión humana (`REVISAR_SCORE_BAJO`): **3.2 %**
- Precisión de lo resuelto: **94.25 %** (13,928 filas con candidato equivocado)
- Filas sin pareja real: 14,908, de las cuales **7,576** se conciliaron por error
- Tiempo de la cascada: **95.65 s** (generación de datos: 7.49 s; exportación Excel: 111.30 s)

## Por escenario de ruido

| Escenario | Filas | % conciliado | % correcto |
|---|---:|---:|---:|
| exacto | 105,156 | 100.0 % | 100.0 % |
| codigo_ruido | 59,884 | 100.0 % | 100.0 % |
| texto_procedimiento | 40,165 | 99.9 % | 95.2 % |
| texto_detalle | 14,864 | 100.0 % | 98.4 % |
| texto_observacion | 10,040 | 100.0 % | 100.0 % |
| degradado | 4,983 | 88.4 % | 2.9 % |
| sin_pareja_ajeno | 7,332 | 0.0 % | 100.0 % |
| sin_pareja_vecino | 7,576 | 100.0 % | 0.0 % |

«% correcto»: con pareja → conciliado al código verdadero; sin pareja → enviado a revisión.

## Tiempo por capa

| Capa | Segundos |
|---|---:|
| C1 | 0.52 |
| C2 | 0.84 |
| C3 | 57.95 |
| C4 | 31.58 |
| C5 | 4.60 |
