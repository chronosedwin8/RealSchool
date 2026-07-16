# ADR-023: Optimización dirigida por evidencia (perfilado + memoización)

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
La escalera de escalabilidad (O6, ADR/Actividad 9) mostró que **todas las etapas
propias del motor escalan de forma lineal** (exponentes 0,9–1,1 frente a docentes)
— no hay ninguna etapa super-lineal que corregir. Aun así, la Actividad de cierre
pide perfilar y eliminar los cuellos de botella reales medidos.

## Evidencia (cProfile sobre ladder-200)
El perfilado del camino de construcción del modelo señaló un único punto caliente
en código propio:

| Función | Llamadas | tottime |
|---|---|---|
| `time_grid.valid_starts` | 10 200 | **0,137 s** (el mayor de los propios) |
| `ortools_solver.new_optional_interval` | 15 470 | 0,126 s (API del solver) |
| `graph_builder._occupiable_slot_count` | 350 | 0,075 s |

`valid_starts` recalculaba el conjunto de inicios válidos una vez por tarea,
aunque casi todas comparten `(duration, same_segment)`: puro trabajo redundante.

## Decisión
Memoizar `TimeGrid.valid_starts` con `functools.cache` sobre una función pura
`_valid_starts(segments, horizon, duration, same_segment)`. La rejilla es inmutable
y hashable, así que la memoización es segura y no cambia ningún resultado (todos
los tests siguen verdes sin tocarse).

## Resultado
Tras el cambio, `valid_starts` **desaparece del top de funciones por tiempo
propio** (de 0,137 s a despreciable). El tiempo restante lo dominan las llamadas
inherentes a la API del solver (`new_optional_interval`, `new_bool_var`), que no
son optimizables desde el dominio. La construcción de ladder-200 (build + lower +
pases) queda en ~300 ms.

## Consecuencias
- **Positivas:** una optimización real, medida y protegida por el gate (O8);
  menos trabajo redundante en instituciones grandes.
- **Se paró aquí a conciencia:** no había un segundo cuello propio que justificara
  más micro-optimización; forzarla sería complejidad sin evidencia. El motor ya
  escala linealmente y el resto del tiempo es del solver.

## Criterios de salida hacia la interfaz desktop (cumplidos)
1. Gate local (`regression_gate.py`) y CI (`.github/workflows/ci.yml`) operativos.
2. Escalera 20→500 documentada; ninguna etapa propia super-lineal (todas ~lineales).
3. Catálogo completo HC-01..HC-12 / SC-01..SC-08 con Tiers operativos (O1, O2).
4. Telemetría, benchmarking estadístico, registro trazable y dashboard (O3, O4, O7).
5. Multi-solver CP-SAT vs CBC/SCIP/HiGHS verificado (O5).
6. Comparación ampliada con Untis sobre 4 años reales (O9).
7. ADRs 019–023 escritos.
