"""Validación en dos fases del proyecto ``.bjs`` (Fase 3, B3), sin jsonschema.

1. **Estructural (sintáctica):** ``check_structure`` verifica, por archivo interno,
   claves obligatorias y tipos sobre el dict crudo — reportando ``archivo + campo``
   antes de instanciar nada. Se ejecuta al abrir el proyecto (``open_project``).
2. **Referencial (semántica):** la instanciación dispara las validaciones **ya
   existentes** (``SchedulingProblem``/``AcademicProblem`` para IDs únicos y
   referencias; ``PluginsConfig.validate`` para el catálogo/Tiers). El
   ``BjsConsistencyChecker`` añade los cruces **entre archivos** (la solución
   referencia tareas/recursos que existen) y emite avisos blandos (recursos sin uso).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import ConfigError
from .project import BjsProject

# archivo interno -> (campo obligatorio, tipo esperado)
_REQUIRED: dict[str, tuple[tuple[str, type], ...]] = {
    "calendar.json": (("grid", dict),),
    "resources.json": (("resources", list),),
    "tasks.json": (("tasks", list),),
}
# archivos opcionales y el tipo de su campo principal
_OPTIONAL: dict[str, tuple[str, type]] = {
    "constraints.json": ("plugins", list),
    "solution.json": ("assignments", list),
}


def check_structure(entries: Mapping[str, Any]) -> None:
    """Valida la forma sintáctica de cada JSON interno (fase estructural)."""
    for fname, fields in _REQUIRED.items():
        if fname not in entries:
            raise ConfigError(f"{fname}: archivo obligatorio ausente en el .bjs")
        doc = entries[fname]
        if not isinstance(doc, dict):
            raise ConfigError(f"{fname}: se esperaba un objeto JSON en la raíz")
        for field, expected in fields:
            if field not in doc:
                raise ConfigError(f"{fname}: falta el campo obligatorio '{field}'")
            if not isinstance(doc[field], expected):
                raise ConfigError(f"{fname}: '{field}' debe ser {expected.__name__}")
    for fname, (field, expected) in _OPTIONAL.items():
        doc = entries.get(fname)
        if doc is not None and (
            not isinstance(doc, dict) or not isinstance(doc.get(field), expected)
        ):
            raise ConfigError(f"{fname}: '{field}' debe ser {expected.__name__}")


def check_consistency(project: BjsProject) -> tuple[str, ...]:
    """Cruces semánticos entre archivos. Lanza ante inconsistencia dura; avisa lo blando."""
    warnings: list[str] = []
    task_ids = {int(t.id) for t in project.problem.tasks}
    resource_ids = {int(r.id) for r in project.problem.resources}

    if project.solution is not None:
        for assignment in project.solution.assignments:
            if int(assignment.task_id) not in task_ids:
                raise ConfigError(
                    f"solution.json: asignación a una tarea inexistente: {int(assignment.task_id)}"
                )
            for rid in assignment.resource_ids:
                if int(rid) not in resource_ids:
                    raise ConfigError(
                        f"solution.json: recurso inexistente en una asignación: {int(rid)}"
                    )

    # Aviso blando: recursos-docente cuyo tag no lo requiere ninguna tarea (sin uso).
    required_tags = {req.tag for task in project.problem.tasks for req in task.requirements}
    for resource in project.problem.resources:
        teacher_tag = next((t for t in resource.tags if t.startswith("teacher#")), None)
        if teacher_tag is not None and teacher_tag not in required_tags:
            warnings.append(
                f"recurso sin uso: {resource.name!r} ({teacher_tag}) no lo requiere ninguna tarea"
            )

    return tuple(warnings)
