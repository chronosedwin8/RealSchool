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

## Otras decisiones de interpretación

| Rareza del dato real | Decisión |
|---|---|
| **Co-docencia** (2 profesores, misma clase) | Untis lo modela como *dos lecciones* con el mismo grupo de estudiantes. Se **fusionan** en un curso con varios docentes; si no, el no-solape del curso lo declararía en conflicto consigo mismo. |
| **Lecciones sin grupo de estudiantes** | **No se fusionan**. Dos profesores con "Extracurricular" no dan la misma clase; fusionarlos los obligaría a coincidir. *(Este fue un bug real: la primera versión los fusionaba.)* |
| **Obligaciones no lectivas** (417: reuniones, preparación, almuerzos, extracurriculares) | Se **excluyen** del modelo. El propio horario de Untis las solapa con clases: ni él las trata como exclusivas. Se reportan, no se planifican. |
| **Pseudo-cursos** (`CL_12-GIB` y 5 más) | Aparecen en las lecciones pero Untis **no los declara** como cursos: son grupos de opción del IB. Como curso unario, uno "necesitaría" 132 períodos en una semana de 75 — el Conflict Explanation Engine lo dijo antes de tocar el solver. No imponen no-solape. |
| **Aulas** | El export dice qué aula *usó* cada materia, no cuál *puede* usar. Se deriva un pool por materia (mediana: 3 aulas). El aula se pide **sesión a sesión**: Untis se la asigna a unas sesiones y a otras no. |

## Resultado: el motor como **auditor**

Aplicando el Validation Engine al horario que **Untis publicó**:

- **413 choques de recurso** (docente/aula/curso ocupado por dos clases a la vez,
  en reloj real). La mayoría involucra los grupos de opción del IB.
- **11 sesiones sin ubicar** (Untis colocó 3.013 de 3.024).

Esta capacidad **no depende de generar el horario**: funciona sobre el que ya
existe, y ningún horario se publica sabiendo dónde está roto.

## Gap Analysis: honestidad sobre lo que aún no logramos

El motor **no produce un horario estrictamente válido** para estos datos dentro
del límite de tiempo. La razón no es de rendimiento (el modelo se construye en
0,4 s): **los datos del colegio contienen los mismos 413 solapes que un modelo
estricto prohíbe**. No estamos resolviendo el problema que Untis resolvió, sino
uno más duro.

Para generar hace falta decidir antes qué son esos 413 solapes: datos a corregir,
o tolerancias reales del colegio (grupos combinados, docencia de apoyo) que hay
que modelar como tales. Los grupos de opción del IB necesitan además un modelo
propio: no son cursos unarios, son conjuntos de alumnos que se reparten.

## Consecuencias técnicas
- El **Modelo Canónico absorbió el colegio real sin cambiar una línea**: una tarea
  puede requerir varios recursos a la vez (co-docencia, clases acopladas de hasta
  7 cursos).
- La rejilla de reloj real queda como requisito no negociable para este colegio.
- Los hallazgos de datos (pseudo-cursos, obligaciones no exclusivas) los produjo
  el propio motor, no una inspección manual.
