# ADR-002: OR-Tools CP-SAT 9.15 como primer solver detrás de la SAL

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
El motor necesita un solver de programación por restricciones para un problema
NP-Hard de timetabling. La especificación (Prompt3 §2.2) exige que el solver
sea un componente reemplazable detrás de una Solver Abstraction Layer.

## Alternativas evaluadas
1. **OR-Tools CP-SAT** — ganador reiterado de la MiniZinc Challenge, gratuito
   (Apache 2.0), restricciones globales nativas (`NoOverlap`, `Cumulative`,
   `AddElement`), paralelismo integrado, wheel nativo cp314.
2. **Gurobi / CPLEX (MILP)** — excelentes en lineal continuo, pero licencia
   comercial y peor ajuste para restricciones lógicas/combinatorias densas.
3. **Choco / OptaPlanner (JVM)** — obligarían a un puente Java.

## Decisión adoptada
OR-Tools CP-SAT 9.15 (`ortools-9.15.6755-cp314`), instanciado exclusivamente
dentro del paquete `sal`. Ninguna otra capa puede importar `ortools`; esta
regla se verificará con una prueba automática de arquitectura.

## Consecuencias técnicas
Modelado 100% en enteros/booleanos (CP-SAT no maneja continuo nativo), lo que
encaja con la rejilla discreta de slots. Si en el futuro se sustituye el
solver, solo se reimplementa `sal` (y el Solver Compiler del CIR).
