# ADR-036: CP-SAT como reparador y pulidor por ventanas; criterios Untis como plugins del puente

**Fecha:** 2026-09-18 · **Estado:** Aceptado

## Contexto

La sección 7 del documento maestro cambia el papel de CP-SAT: deja de generar
horarios y pasa a **reparar** (cambio mínimo), **pulir** un horario ya bueno y
**demostrar infactibilidad**. También pedía cinco extensiones del motor
congelado: dobles como variable, desglose por criterio, secuencias, pool
ordenado con costes y contadores por media jornada.

Dos hechos condicionan el diseño:

1. El modelo canónico usa **slots de un minuto** (el único reloj común a las 8
   rejillas, ADR-016). Los plugins del catálogo miden huecos y consecutivos en
   slots, es decir en minutos; los criterios Untis se miden en **períodos**.
2. Congelar todo el horario con `ReOptimizationEngine` crea variables booleanas
   de inicio para las 1.676 sesiones. Funciona (ADR-017), pero no escala para
   pulir muchas ventanas seguidas.

## Alternativas evaluadas

1. **Extender el catálogo del motor** con plugins Untis — rompe la congelación
   de `engine-1.0` para conceptos que solo entiende el producto.
2. **Plugins del puente** (`bridge/plugins.py`) — *adoptada*. El SDK de plugins
   ya es el punto de extensión; `bridge` conoce la geometría Untis y la pasa
   precalculada. El motor no se toca salvo el desglose por criterio.
3. **Pulir el horario entero con CP-SAT** — descartada: modelo enorme y objetivo
   en minutos, divergente del evaluador de referencia.

## Decisión adoptada

1. **Subproblema de ventana** (`bridge/repair.py`): las tareas de la ventana,
   libres, más una tarea *bloqueadora* fija por cada asignación congelada que
   comparte recurso con ellas. Es exacto para las duras y pequeño.
2. **Reparar** (`repair`): ventana = sesiones en choque + no colocadas; objetivo
   de cambio mínimo (mover de hora pesa 10, cambiar de aula 3). Si no hay
   solución, se amplía con las sesiones vecinas (mismo profesor o clase, mismo
   día). Sobre el horario publicado por Untis: 7 choques → 0 en 0,6 s, moviendo
   6 de 1.676 sesiones y sin cambiar ningún aula.
3. **Pulir** (`polish`): ventana = la semana entera de una clase, de peor a
   mejor según el evaluador. CP-SAT minimiza, **en períodos**, los huecos de la
   clase y los de cada profesor que la atiende (sus sesiones en otras clases son
   ocupación fija), los dobles pedidos y un cambio mínimo de peso 1. **Una
   ventana solo se acepta si el número de evaluación completo baja**: el
   evaluador de referencia es el juez, así que CP-SAT puede ver solo una parte
   del objetivo sin riesgo de empeorar el conjunto.
4. **Plugins del puente**, genéricos y alimentados con geometría precalculada:
   `MinimalChangePlugin`, `OrderedPoolPlugin` (pool ordenado con costes: cadena
   de aulas alternativas), `ForbiddenPairsPlugin` (secuencias: "A antes que B el
   mismo día"), `MinPairsPlugin` (mínimo de dobles) y `PeriodGapsPlugin`
   (huecos en períodos, varias entidades por instancia porque el registro exige
   nombres únicos).
5. **Única extensión del motor:** `MetricsEngine.breakdown(solution) ->
   EvaluationBreakdown`, aditiva. Agrupa `solution.penalties` por etiqueta; como
   cada término lleva por etiqueta su criterio de la ponderación, el desglose
   suma exactamente el `objective_value`. `bridge/objective.py` lo lleva al
   vocabulario de la ponderación y un test exige que ninguna etiqueta emitida
   quede sin nombre Untis.

## Consecuencias técnicas

- Reparar + 60 s de pulido sobre el horario publicado por Untis (2025-2026):
  de 7 choques y 118.418 puntos blandos a **0 choques y 86.904** (−28 %): huecos
  de clase 264 → 179 y de profesor 1.174 → 938.
- Extensiones del documento maestro sin implementar en CP-SAT, por decisión:
  *dobles como variable entera con partición dinámica* (el mínimo de dobles por
  parejas de inicios cubre el caso real, donde los bloques son de 2) y
  *contadores por media jornada / materias principales*. La heurística los
  optimiza exactamente y el guardián del pulido impide que CP-SAT los empeore.
  `MinPairsPlugin` cuenta parejas adyacentes: con un tramo de 3 cuenta 2 donde
  el evaluador cuenta 1 doble; es una aproximación consciente, cubierta por el
  guardián.
- La demostración de infactibilidad sigue en el pipeline existente
  (`ConstraintGraphBuilder`, `conflict_explanation`), sin cambios.
