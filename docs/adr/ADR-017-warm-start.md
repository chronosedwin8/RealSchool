# ADR-017: Warm start (siembra con un horario conocido)

**Fecha:** 2026-07-14 · **Estado:** Aceptado

## Contexto
ADR-016 dejó el reto abierto: el motor no genera desde cero un horario para
~1.900 clases reales frente a las heurísticas maduras de Untis. Pero sí sabe
reconstruir y validar el horario de Untis. La propuesta: **sembrar la búsqueda**
con ese horario para que el motor lo **mejore/repare** en vez de reinventarlo.

## Decisión

### 1. `add_hint` en la SAL
`ISolver.add_hint(var, value)` sugiere un valor inicial para una variable. No es
una restricción: el solver puede ignorarlo. `ORToolsSolver` lo traduce a
`CpModel.add_hint`; `FakeSolver` lo registra. Es la única extensión necesaria, y
queda **aislada tras la SAL**: el dominio y el motor no conocen CP-SAT.

### 2. `warm_start_hints(context, solution)` y `SchedulingEngine.solve(..., warm_start=)`
Traduce una solución conocida a hints en el vocabulario del modelo: el inicio de
cada tarea (`tstart`) y los recursos que usó (`assign`). Es un hint **parcial**:
CP-SAT lo completa. El pipeline aplica los hints tras compilar el CIR, antes de
resolver.

### 3. Duración por sesión (corrección del adaptador Untis)
Un acople puede tener sesiones de duración distinta (una de 45 min y una de 20).
Se calcula la duración —y por tanto los inicios válidos— **por sesión**, no por
acople. Sin esto, el inicio real de una sesión caía fuera de su dominio y la
solución de Untis no validaba.

## Resultado medido (4 cursos reales, límite 30 s por resolución)

| Curso | Clases | En frío | Sembrado | Clases conservadas |
|---|---|---|---|---|
| 2023–2024 | 1.822 | sin horario | **óptimo, 0 conflictos** | 1.718 (94%) |
| 2024–2025 | 1.889 | sin horario | **óptimo, 0 conflictos** | 1.795 (95%) |
| 2025–2026 | 1.835 | sin horario | **óptimo, 0 conflictos** | 1.718 (94%) |
| 2026–2027 | 1.930 | sin horario | **óptimo, 0 conflictos** | 1.869 (97%) |

Cada horario de Untis tenía decenas de choques bajo no-solape estricto
(profesores en dos sitios por las clases combinadas del IB). Sembrado, el motor
los **repara a un horario válido** moviendo el mínimo de clases.

## Consecuencias técnicas
- **El reto de ADR-016 se resuelve por la vía correcta:** no compitiendo con las
  heurísticas de Untis desde cero, sino **partiendo de su horario y mejorándolo**.
- **Valor de producto real:** un colegio no quiere un horario radicalmente
  distinto cada año; quiere corregir el vigente con el mínimo cambio. El warm
  start entrega exactamente eso, y el cambio es explicable clase por clase.
- **Aislamiento intacto:** una sola extensión (`add_hint`) tras la SAL; ninguna
  capa de dominio conoce el solver.
- **Deuda:** el objetivo actual es de pura factibilidad. Añadir un objetivo de
  calidad (minimizar huecos, cambios de aula) permitiría al warm start no solo
  reparar, sino **mejorar** el horario de Untis de forma medible.
