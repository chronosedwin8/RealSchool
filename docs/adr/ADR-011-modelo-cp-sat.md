# ADR-011: Modelo matemático CP-SAT y ORToolsSolver

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
La Fase 7 introduce el solver real. Prompt3 §2.1.1 exige elegir la formulación
matemática más eficiente y **justificarla**. Prompt3 §2.2 exige que el solver
sea la única capa que conoce OR-Tools.

## Decisiones adoptadas

### 1. `ORToolsSolver` como único punto de contacto con OR-Tools
Implementa `ISolver` traduciendo sus primitivas (lineal, all-different, bool-or,
implicación, minimizar) a CP-SAT, y mantiene el mapeo handle opaco -> variable
nativa. Es el ÚNICO módulo que importa `ortools` (verificado por
`tests/test_architecture.py`). Se importa explícitamente y **no** se reexporta
en `sal/__init__`, para que `dsl`/`cir`/`pipeline` no arrastren `ortools` al
usar `sal.interface`.

### 2. Estrategia de variables: modelo booleano start/assign (justificación)
- **Variables:** `start[t,s]` (la tarea inicia en el slot) y `assign[t,r]` (usa
  el recurso), ambas booleanas; enteras solo para holguras/objetivo.
- **Por qué esta formulación y no `IntervalVar`/`NoOverlap`:**
  - *Mantenibilidad/coherencia:* se integra directamente con el stack ya
    construido (DSL lineal -> CIR -> `ISolver`) y con el vocabulario que usan los
    plugins; no requiere extender DSL/CIR/SAL con intervalos.
  - *Portabilidad:* al usar solo restricciones lineales y booleanas, la misma
    formulación es implementable por un solver MILP (Gurobi) sin globals de CP.
  - *Corrección demostrada:* validada con oráculos de óptimo conocido.
- **Trade-off / rendimiento:** el no-solape por linealización de ocupación
  genera O(tareas x recursos x slots) variables auxiliares. Para instituciones
  grandes, una reformulación con `OptionalIntervalVar` + `NoOverlap` (más
  compacta y con mejor propagación) es la optimización natural; se documenta
  como trabajo de la Fase 11 (rendimiento), detrás de la SAL, sin tocar dominio
  ni plugins.

### 3. No-solape como plugin estructural
`ResourceNoOverlapPlugin` (capacidad 1) expresa "un recurso, una tarea a la vez"
linealizando `occ = assign AND cover` y `sum_t occ[r,k] <= 1`. Es una regla de
correctitud; `default_structural_plugins()` la ofrece para activarla siempre.

### 4. Determinismo y telemetría
`SolverConfig` expone `random_seed`, `num_search_workers` y
`max_time_in_seconds`. Con semilla fija y un worker, la resolución es
reproducible (verificado en pruebas de determinismo).

## Consecuencias técnicas
- **Aislamiento real del solver** confirmado end-to-end.
- **Pruebas de rigor del modelo:** oráculos (óptimo manual), determinismo y
  metamórficas (permutar la entrada no cambia el óptimo).
- **Deuda registrada:** reformulación por intervalos para escala (Fase 11).
