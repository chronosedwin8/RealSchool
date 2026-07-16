# ADR-022: Multi-solver — backends MILP (CBC/SCIP/HiGHS) vía la SAL

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
La Actividad 7 pide comparar el mismo dataset en distintos solvers (HiGHS, CBC,
SCIP, Gurobi, CP-SAT). La SAL (`ISolver`) prometía justamente esto: cambiar de
solver sin tocar el dominio. Faltaba una implementación no-CP-SAT que lo probara.

## Decisión

### 1. `sal/mip_solver.py` — `MipSolver`
Implementa `ISolver` sobre `ortools.linear_solver.pywraplp`, con backend
seleccionable (`CBC`, `SCIP`, `HiGHS`, `GUROBI`). Es la **segunda y última**
frontera autorizada a importar `ortools` (el test de arquitectura ya solo exige
que viva bajo `sal/`). En el entorno actual CBC/SCIP/HiGHS vienen incluidos en
OR-Tools; Gurobi no (sin licencia) y se detecta dinámicamente.

### 2. Qué traduce y qué no
Los solvers MILP no tienen intervalos ni restricciones globales nativas. Por eso:
- `new_interval`, `new_optional_interval`, `add_no_overlap`, `add_all_different`
  y `new_int_var_from_values` (dominio con huecos) lanzan `UnsupportedOperation`.
- `bool_or` e `implication` **sí** se linealizan (triviales sobre 0/1).
- Los benchmarks MIP usan por eso la **formulación booleana** del no-solape
  (`ResourceNoOverlapPlugin`, `boolean_starts=True`): un modelo puramente 0/1
  lineal, sin `tstart` de dominio enumerado, que traduce directamente.

### 3. Warm start y límites
`add_hint` acumula sugerencias y las aplica con `SetHint` al resolver;
`max_time_in_seconds` se traduce a `set_time_limit`.

### 4. Verificación diferencial
Un test resuelve la misma formulación booleana con CP-SAT y con cada backend MILP
y exige el **mismo óptimo**. `scripts/bench.py solvers <preset>` mide tiempo,
score y RAM de todos los backends sobre el mismo dataset.

## Consecuencias
- **Positivas:** la promesa de la SAL, cumplida y verificada; comparación
  multi-solver disponible sin dependencias nuevas.
- **Negativas / límites:** la formulación booleana MIP crece con el horizonte, así
  que CBC/SCIP son lentos en instancias grandes (esperado: CP-SAT domina en
  scheduling; el valor aquí es la **evidencia**, no la paridad). Gurobi queda
  disponible sin código nuevo si aparece una licencia.
