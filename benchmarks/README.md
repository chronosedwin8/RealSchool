# Benchmarks

Framework de medición del motor. El código vive en
[`src/scheduling_platform/benchmarks/`](../src/scheduling_platform/benchmarks/)
(datasets sintéticos + runner con telemetría) y se ejecuta con:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark.py [small|medium|large|xl] [segundos]
```

Imprime latencia por etapa, tamaño del modelo, RAM pico y calidad del horario, y
vuelca el resultado en JSON para comparar entre versiones.

## Datasets

Instituciones sintéticas **factibles por construcción** (el generador rechaza
parámetros imposibles). Cada grupo tiene un *pool* reducido de aulas: un aula no
es intercambiable con cualquier otra, y modelarlo así mantiene el modelo acotado
sin perder realismo.

| Preset | Docentes | Aulas | Grupos | Clases |
|---|---|---|---|---|
| `small` | 20 | 15 | 15 | 315 |
| `medium` | 80 | 60 | 60 | 1.260 |
| `large` | 250 | 150 | 150 | 2.550 |
| `xl` | **500** | **300** | **1.500** | **7.500** |

> Los datasets operan al ~71% de ocupación de aulas. Al 100% el problema se
> convierte en un empaquetado perfecto: brutalmente difícil y ajeno a la
> realidad de cualquier colegio.

## Resultado en la escala objetivo (DS-XL)

Con la formulación por intervalos y el modo compacto (ADR-015):

```
Tamaño:      7500 clases, 2300 recursos, horizonte 35
Modelo:      52.500 variables, 24.800 restricciones
Construir:   6.658 ms
Lowering:      900 ms
Pases:         374 ms
Compilar:    1.587 ms
Búsqueda:   17.324 ms
TOTAL:      31.740 ms
RAM pico:       75 MB
Resultado:  optimal — horario válido, 0 violaciones duras
```

**La escalabilidad objetivo de Prompt3 §4 se cumple.** Antes de la Fase 11, la
misma instancia tardaba 342s y no encontraba solución: el detalle del antes y
después está en [ADR-015](../docs/adr/ADR-015-formulacion-por-intervalos-y-escala.md).
