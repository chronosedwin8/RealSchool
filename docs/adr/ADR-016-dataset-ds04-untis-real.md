# ADR-016: DS-04 Colegio Alemán — importador de Untis y modelo de reloj real

**Fecha:** 2026-07-14 · **Estado:** Aceptado

## Contexto
El framework de benchmarking (`FasesPosteriores/ARCHITECTURE_AND_BENCHMARK.md`)
pide el dataset **DS-04 Colegio Alemán** como caso crítico de comparación frente
a Untis. Se dispone del **export real** (`untis.xml`, XmlInterface 3.0) del
Colegio Alemán de Barranquilla, curso 2025-2026: 116 docentes, 95 aulas, 64
cursos, 1.235 lecciones, 3.024 clases semanales y 8 jornadas.

## Decisión central: la rejilla es de **tiempo de reloj**, no de números de período

Las 8 jornadas usan **horas distintas para el mismo número de período**. El
período 5 de Kinder (10:00–10:45) no coincide con el período 5 de Bachillerato
(09:35–09:55, un recreo): coincide con su **período 6**.

Modelar por número de período declararía simultáneas clases que no lo son, y no
simultáneas las que sí. La rejilla canónica pasa a ser de **minutos reales**
(5 días × 680 min = 3.400 slots), y cada clase:

- **dura** lo que dura su período real (45 min domina, pero hay de 10, 25, 30 y 60);
- **puede empezar** en cualquier período de su jornada con esa misma duración.

Esto encaja exactamente con las piezas de la Fase 11: `EnumDomain` (dominios con
huecos) e intervalos opcionales. El modelo resultante: 20.344 variables, se
construye y compila en **0,4 s**.

## Decisión: clases compartidas (Kopplungen) como acoples paralelos

Untis reparte a los alumnos de uno o varios cursos en **N grupos paralelos**
durante una materia: N profesores dan la clase **a la vez**, cada uno en su
aula. Untis lo marca con un **grupo de estudiantes** (`SG_...`) compartido entre
las líneas; una línea combinada (un profesor, varios cursos) une transitivamente
los cursos del acople.

- **Detección:** union-find sobre las lecciones. Se unen dos líneas si comparten
  grupo de estudiantes, o si comparten un curso con la misma materia y
  periodicidad (la línea combinada enlaza los cursos). Resultado: el alemán K4
  queda como **un acople de 5 profesores y 4 cursos**, tal como se ve en Untis.
- **Modelado:** cada acople = **una tarea** que ocupa todos sus profesores (a la
  vez), todos sus cursos declarados, y **tantas aulas como profesores paralelos**
  (`ResourceRequirement(roompool, quantity=N)`). El Modelo Canónico ya soporta
  requerir N recursos de un pool: no hubo que tocar nada.
- 595 acoples, 124 clases compartidas, hasta **9 profesores en paralelo**.

## Otras decisiones de interpretación

| Rareza del dato real | Decisión |
|---|---|
| **Obligaciones no lectivas** (417) | Se **excluyen**. El propio horario de Untis las solapa con clases: ni él las trata como exclusivas. Se reportan, no se planifican. |
| **Pseudo-cursos** (`CL_12-GIB` y 5 más) | Aparecen en las lecciones pero Untis **no los declara** como cursos: son grupos de opción del IB. No imponen no-solape de curso. |
| **Aulas** | El export dice qué aula *usó* cada materia, no cuál *puede*. Se deriva un pool por materia; el nº de aulas por sesión = nº de profesores paralelos. |

## Resultado: el motor como **auditor** (y auditor de sí mismo)

Aplicando el Validation Engine al horario que **Untis publicó**, con el modelo
correcto: **0 choques de recurso** sobre las 1.683 sesiones. El motor reproduce
y valida un horario real de colegio completo, de forma independiente del solver.

Una versión anterior de este análisis reportó **413 choques**. Eran un **error
de modelado nuestro** (fusionar las clases compartidas como co-docencia en un
aula, exigiendo una sola aula). Corregido el modelo, desaparecen. El valor de
una auditoría independiente es que también nos audita a nosotros.

## Gap Analysis: honestidad sobre la generación

El motor **no produce un horario desde cero** para estos datos dentro del límite
de 90 s. No es un problema de modelado ni de infactibilidad: acabamos de validar
la solución de Untis, luego el problema **es factible** y el motor la reconoce
como correcta. Simplemente no la reencuentra por su cuenta en ese tiempo — es un
problema NP-difícil de 1.683 clases reales frente a décadas de heurísticas
propietarias de Untis.

El siguiente paso natural: **warm start** con el horario de Untis (que el motor
ya sabe reconstruir) para que el motor lo *mejore* en vez de reinventarlo.

## Consecuencias técnicas
- El **Modelo Canónico absorbió el colegio real sin cambiar una línea**: una tarea
  puede requerir varios profesores, varios cursos y **N aulas** a la vez.
- La rejilla de **reloj real** y el modelo de **clases compartidas** quedan como
  requisitos no negociables para este colegio.
- Los hallazgos de datos (pseudo-cursos, obligaciones no exclusivas) y la
  corrección de nuestro propio error los produjo el motor, no una inspección
  manual.
