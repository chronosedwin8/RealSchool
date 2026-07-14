# ADR-009: Optimization Pipeline, Graph Builder y Conflict Explanation

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
Prompt3 §3 exige un pipeline que, antes de invocar al solver, detecte
infactibilidades estructurales y, ante un resultado infactible, produzca una
explicación legible en lugar de un "INFEASIBLE" mudo.

## Decisiones adoptadas

### 1. El Graph Builder analiza el problema canónico, no el CIR
Las infactibilidades más útiles (tag sin proveedor, sobre-suscripción de un
docente, demanda > oferta de aulas) se expresan sobre recursos con tags y
capacidades y tareas con duración/disponibilidad; ese es el nivel canónico
(`SchedulingProblem`), que además conserva los nombres para mensajes legibles.

### 2. Solo condiciones necesarias (sin falsos positivos)
Los cuatro chequeos (tag sin proveedor, dominio temporal vacío,
sobre-suscripción de recurso unario, demanda global > oferta) son condiciones
necesarias: si se violan, el problema es demostrablemente infactible. No
pretenden ser completos (el solver detecta el resto); pretenden no equivocarse.

### 3. Conflict Explanation Engine como único traductor de infactibilidad
Un solo componente convierte tanto los hallazgos del Graph Builder como las
`StructuralContradictionError` del CIR (Fase 4) en un `ConflictReport`
renderizable. Garantiza que ninguna ruta de infactibilidad quede sin explicar.

### 4. Pipeline con inyección de dependencias del solver
`OptimizationPipeline` recibe el `ISolver` como parámetro (DI). En pruebas se
usa `FakeSolver`; en producción, `ORToolsSolver` (Fase 7). El pipeline se
detiene antes de compilar/resolver si el análisis pre-solver es infactible, y
antes de resolver si los pases del CIR detectan una contradicción.

## Consecuencias técnicas
- **Detección temprana y barata:** se evita lanzar el solver sobre problemas
  imposibles; el 100% del catálogo de instancias infactibles produce una
  explicación accionable.
- **Alcance de la fase:** la extracción de la solución, el cálculo de métricas y
  la reoptimización se difieren a las Fases 7/9/10; el pipeline ya deja los
  puntos de extensión (var_map, status) preparados.
