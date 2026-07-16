# Tutorial 1 — Hola, mundo

En 5 minutos: instalar, diagnosticar el entorno, importar datos y generar un
primer horario, todo con el CLI `schedule-engine`.

## Instalar

```bash
pip install -e ".[cli]"
```

## Diagnosticar el entorno

```bash
schedule-engine doctor
```

Reporta Python, hardware y qué solvers están disponibles (CP-SAT, CBC, SCIP,
HiGHS). Si CP-SAT aparece como disponible, ya puedes resolver.

## Importar un horario de Untis

```bash
schedule-engine convert untis.xml colegio.bjs
```

Traduce el XML nativo de Untis al contenedor `.bjs` (ver
[Formato .bjs](../architecture/bjs_format.md)).

## Inspeccionar y validar

```bash
schedule-engine project info colegio.bjs
schedule-engine project validate colegio.bjs --strict
```

## Generar un horario

```bash
schedule-engine generate colegio.bjs --quick
```

`--quick` busca la primera solución factible. Para optimizar la calidad con las
reglas configuradas, usa `optimize`; para ver el progreso en vivo (útil para una
GUI), añade `--json-stream`.

## Bajo el capó (API)

El CLI es una capa delgada sobre el motor. Este es el Modelo Canónico mínimo que
representa "un docente, un aula, dos clases":

```python
from scheduling_platform.core import (
    SchedulingProblem, TimeGrid, Resource, ResourceId,
    Task, TaskId, ResourceRequirement,
)

problem = SchedulingProblem(
    grid=TimeGrid.from_segment_lengths([4]),  # un día de 4 períodos
    resources=(
        Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
        Resource(ResourceId(1), "Aula", frozenset({"room"})),
    ),
    tasks=tuple(
        Task(TaskId(i), f"Clase {i}", 1,
             (ResourceRequirement("teacher#0"), ResourceRequirement("room")))
        for i in range(2)
    ),
)
assert len(problem.tasks) == 2
assert problem.horizon == 4
```

**Siguiente:** [escribe tu primera restricción](02-first-constraint.md).
