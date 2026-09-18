# ADR-035: Evaluador de referencia en el dominio y fidelidad del puente

**Fecha:** 2026-09-18 · **Estado:** Aceptado

## Contexto

La fase R2 exige dos cosas: (1) que el puente `untis_model → core` sea fiel, con
el criterio del documento maestro "el `ValidationEngine` da 0 duras sobre el
horario Untis de cada curso", y (2) un **número de evaluación** desglosado por
criterio, el mismo que optimizará la heurística (R3) y mostrarán las ventanas de
Evaluación y Diagnóstico (R4).

Al medir el export real 2025-2026 aparecieron tres hechos que obligan a decidir:

1. **El horario publicado por Untis tiene 7 choques de profesor reales**
   (lección contra lección, medidos sobre el reloj de pared): grupos partidos de
   IB en 12.º, la vigilancia de salida ("SALIDA"), dirección de grupo. Son
   choques que el planificador aceptó. "0 duras" es **inalcanzable** con estos
   datos sin falsear la traducción.
2. **Comparar por número de período es incorrecto.** Las 8 rejillas no comparten
   horas: el mismo número de período cae a horas distintas. Medir por número
   daba 29 choques falsos y ocultaba otros.
3. **El XmlInterface no marca los recreos.** Sin esa marca, un recreo libre
   entre dos clases cuenta como hueco: 493 huecos de clase en el horario de
   Untis, y la optimización intentaría evitar dar clase a ambos lados del
   recreo.

## Alternativas evaluadas

1. **Evaluador en `bridge`, sobre la `Solution` canónica** (lo que sugería el
   documento maestro) — la heurística no puede importar `bridge` (regla de
   fronteras, ADR-034) y trabaja en períodos, no en minutos; tendría que
   duplicar la semántica sin una referencia común.
2. **Evaluador en `untis_model`**, sobre el `Timetable` en vocabulario Untis —
   *adoptada*. Es lógica de dominio pura (Untis calcula el número de
   evaluación), no depende del motor y la comparten todos.
3. **Mantener "0 duras" y excluir las lecciones en choque** — descartada:
   ocultaría datos reales y haría el criterio de aceptación decorativo.

## Decisión adoptada

1. **`untis_model/evaluation.py` es el evaluador de referencia.** Define cada
   uno de los 38 deslizadores de la ponderación como una función que produce
   `Violation`s con salto a la lección o la celda. Cuenta en **períodos** sobre
   la *rejilla propia* de cada entidad (la de la clase; la más usada por el
   profesor); una sesión ocupa todos los períodos de esa rejilla que solapa en
   el reloj de pared. Duras aparte (`Evaluation.clashes`): choques de recurso
   entre lecciones distintas y deseos −3/+3 incumplidos. La heurística (R3)
   debe reproducirlo incrementalmente, y un test lo exige.
2. **Criterio de aceptación de R2 reformulado, más estricto:** el puente no
   produce **ningún falso positivo**. Tres métodos independientes —el
   evaluador, el `ValidationEngine` del motor sobre la traducción canónica y un
   barrido directo del reloj de pared— deben ver exactamente los mismos
   choques. Hoy los tres ven los mismos 7 y nada más (`tests/test_bridge.py`,
   `tests/test_evaluation.py`).
3. **Recreos deducidos** (`untis_model/breaks.py`): un período más corto que el
   dominante de su rejilla en el que ninguna clase tiene lección es un recreo.
   Conservador (nunca marca un período ocupado, propiedad verificada con
   Hypothesis), explícito (paso de dominio aparte, `xml.py` sigue siendo un
   serializador 1:1) y corregible en la ventana Rejilla. Marca los recreos de
   20 min de las 8 rejillas y respeta los períodos cortos de dirección de grupo
   (10–30 min, con 20–100 lecciones cada uno).
4. **Obligaciones no lectivas fuera de la exclusividad.** Una lección sin
   clases ni grupo de alumnos no choca: el propio Untis las solapa con clases
   (34 veces en el export). Se excluyen de la traducción por defecto
   (`include_duties=False`), igual que hacía el adaptador de ADR-016.
5. **Optimización de profesores opt-in**, como en el diálogo de Untis: sin ella,
   una línea sin profesor no ocupa a nadie; con ella, pide uno del pool de su
   materia contando también a los profesores fijos que llevan la etiqueta.

## Consecuencias técnicas

- Número de evaluación del horario publicado por Untis (curso 2025-2026, con
  recreos deducidos y la ponderación por defecto): 4 períodos sin colocar
  (dos obligaciones), 7 choques, 264 huecos de clase y 1.174 de profesor. Es la
  vara con la que R3 comparará la heurística, en igualdad de condiciones.
- El evaluador tarda ~80 ms sobre 1.676 sesiones: sirve para verificar, no para
  el bucle interno de la heurística, que necesita deltas incrementales.
- Dos puntos del puente corregidos por las pruebas de ida y vuelta con datos
  reales: el aula no va siempre en la línea 0 (77 lecciones la llevan en otra
  línea) y las sesiones se emparejan con sus celdas por duración, no por
  posición.
- Deuda: los criterios de almuerzo, materias principales y secuencias existen
  en el evaluador pero no tienen aún término CP-SAT; el pulido CP-SAT (R3) solo
  optimiza los que el motor expresa (ver las extensiones de la sección 7).
