# ADR-013: Motor, Validation Engine y Telemetría

**Fecha:** 2026-07-14 · **Estado:** Aceptado

## Contexto
Faltaba cerrar el circuito: convertir las variables del solver en un horario,
explicar su score, y —requisito rescatado de `contextobase.md`— **no confiar
únicamente en el solver**. Además, Prompt3 §6.1 pide telemetría y determinismo.

## Decisiones adoptadas

### 1. `SchedulingEngine` como fachada con el solver inyectado
API pública única: `SchedulingEngine(registry, ORToolsSolver).solve(problem, config)`
devuelve un `EngineResult` con estado, horario, informe de penalizaciones,
validación y telemetría. El solver entra como *factory* (`Callable[[], ISolver]`),
de modo que **la capa `engine` no importa `ortools`**: sigue habiendo una sola
línea `import ortools` en todo el repositorio.

### 2. `SolutionBuilder` sobre el vocabulario de variables, no sobre CP-SAT
Reconstruye la `Solution` canónica leyendo las variables `start`/`assign` a
través del `var_map` (key → handle) y de `ISolver.value`. No conoce CP-SAT; si
mañana el solver cambia, el builder no se toca. El adaptador académico completa
el último tramo (`to_schedule`), verificado end-to-end.

### 3. Validation Engine **independiente del modelo matemático**
Re-verifica el horario ya construido sin mirar variables ni restricciones del
solver: cobertura de tareas, inicios válidos, requerimientos satisfechos por tag
y capacidad de cada recurso por período. Es una segunda implementación,
deliberadamente redundante: si el modelo tuviera un error de formulación, esta
capa lo delataría. Se prueba con **soluciones corrompidas a propósito** (docente
duplicado, aula faltante, tarea sin asignar, inicio inválido).

### 4. Informe de Penalizaciones con invariante verificable
`SolutionInspector` evalúa cada término de holgura sobre la solución y desglosa
la penalización por criterio. **Invariante:** la suma del informe debe coincidir
exactamente con el valor de la función objetivo — verificado en las pruebas.
Esto responde "¿por qué este horario puntúa así?" con números auditables.

### 5. Telemetría por etapa en el pipeline
`Telemetry` cronometra análisis, lowering, pases, compilación y búsqueda, y
reporta el tamaño del modelo (variables, restricciones antes/después de los
pases). Alimenta directamente el framework de benchmarking planificado.

## Consecuencias técnicas
- El motor es utilizable como librería: una llamada, un resultado completo.
- La calidad de un horario es **explicable y auditable**, no un número opaco.
- La telemetría hace medible el efecto de los Optimizer Passes.
- **Redundancia deliberada:** validar dos veces (solver + Validation Engine)
  cuesta un recorrido O(tareas × recursos × duración), despreciable frente a la
  búsqueda, a cambio de detectar errores de modelado que de otro modo pasarían
  silenciosamente a producción.
