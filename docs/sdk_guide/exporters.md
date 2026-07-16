# Crear exportadores

Un exportador toma una `Solution` (y/o el `SchedulingProblem`) y produce un
formato de salida: JSON, YAML, el contenedor `.bjs`, o el tuyo (Excel, PDF, iCal).

## Lo que ya existe

```python
from scheduling_platform.serialization import (
    solution_to_json, solution_to_yaml,     # texto abierto
    solution_to_dict,                        # dict plano (base de todo)
)
```

- `solution_to_dict` es la **base**: convierte la solución a un dict plano
  (asignaciones: `task_id`, `start`, `resource_ids`). Cualquier exportador parte de
  aquí.
- El `.bjs` guarda `solution.json` (vía `solution_to_dict`) dentro del contenedor
  atómico. Ver [Formato .bjs](../architecture/bjs_format.md).

## Escribir un exportador propio

```python
from scheduling_platform.serialization import solution_to_dict

def solution_to_csv(problem, solution) -> str:
    lines = ["task_id,start,resources"]
    for a in solution.assignments:
        rids = " ".join(str(int(r)) for r in a.resource_ids)
        lines.append(f"{int(a.task_id)},{int(a.start)},{rids}")
    return "\n".join(lines)
```

Para nombres humanos (docente, aula, materia) en vez de IDs, usa el
`AcademicTranslation.to_schedule(...)` del adaptador, que reconstruye el horario
legible desde la solución canónica.

## Disciplina de streams (si lo integras al CLI)

Si expones tu exportador como comando, respeta el contrato:
**datos por `stdout`, logs por `stderr`**. Devuelve el dato en el `payload` del
`CommandResult`; el dispatcher lo emite. Nunca escribas en `stdout` desde el
comando. Ver [Capa de Aplicación](../reference/application.md).

## Probarlo

Round-trip donde aplique (`solution_to_dict` → `solution_from_dict` → igualdad);
para formatos de solo-salida, compara contra una salida esperada fija (patrón en
`tests/test_serialization.py`).

Referencia: [API — serialization](../reference/serialization.md).
