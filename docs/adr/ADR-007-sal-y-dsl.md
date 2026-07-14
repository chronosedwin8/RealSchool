# ADR-007: Solver Abstraction Layer y Constraint DSL

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
El motor debe (Prompt3 §2.2/§2.3) aislar el solver detrás de una interfaz y
permitir que los plugins expresen restricciones de forma declarativa, para que
la traducción a llamadas del solver sea uniforme, portable y analizable.

## Decisiones adoptadas

### 1. Variables del solver como handles opacos (`SolverVar = int`)
`ISolver` crea variables y devuelve un entero opaco; cada implementación
mantiene su propio mapeo handle -> variable nativa.
- **Alternativa:** exponer objetos de variable del solver (genéricos por tipo).
  Filtraría tipos de OR-Tools a la interfaz y complicaría el tipado.
- **Consecuencia:** ninguna capa superior ve tipos nativos; `ORToolsSolver`
  (Fase 7) y un `GurobiSolver` futuro implementan el mismo contrato.

### 2. Superficie de `ISolver` de nivel lineal/booleano
`new_bool_var`, `new_int_var`, `add_linear`, `add_all_different`, `add_bool_or`,
`add_implication`, `minimize`, `solve`, `value`, `objective_value`.
- **Por qué:** denominador común expresable por CP-SAT y por solvers MILP
  (linear + indicadores). Restricciones globales adicionales (`NoOverlap`,
  `Cumulative`) se añadirán en la Fase 7 con su modelado CP-SAT específico.

### 3. DSL sin sobrecarga de `==`
`Var`/`LinearExpr` son hashables y se usan como claves; sobrecargar `==` para
construir relaciones rompería el hashing. La igualdad de modelado se expresa
con `.eq(...)`; las comparaciones de orden (`<=`, `>=`, `<`, `>`) sí se
sobrecargan porque no afectan al hashing. `<`/`>` se bajan a `<=`/`>=` usando
la integralidad de las variables.

### 4. Compilador DSL -> ISolver como seam del "Solver Compiler"
`DslToSolverCompiler` baja el DSL directamente al solver en la Fase 3. En la
Fase 4 se interpondrá el CIR (DSL -> CIR -> pases -> Solver Compiler): el
compilador pasará a consumir el CIR optimizado sin alterar ni el DSL ni la SAL.

## Consecuencias técnicas
- **Aislamiento verificado:** `sal` es la única capa que podrá importar
  `ortools`; en la Fase 3 aún no lo hace (solo `FakeSolver`).
- **Testabilidad:** el `FakeSolver` registra el modelo y un arnés de contrato
  (`assert_isolver_contract`) fija las propiedades que la Fase 7 reutilizará.
- **Alcance acotado:** formas booleanas anidadas, `NoOverlap`, consecutividad y
  reificación general se difieren a la Fase 4/7 con su bajada correspondiente.
