"""Genera un proyecto ``.bjs`` de demostración para probar la app de escritorio.

Un colegio pequeño: 5 días x 6 períodos, 4 docentes, 3 grupos, 3 aulas y varias
materias. Sirve para abrir ``schedule-desktop`` y ver el flujo completo sin tener
un export de Untis a mano.

Uso:  .venv\\Scripts\\python.exe scripts\\demo_project.py [ruta.bjs]
"""

from __future__ import annotations

import sys
from pathlib import Path

from scheduling_platform.application import BjsProject, save_project
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)

_DAYS = 5
_PERIODS = 6

# (docente, materia, sesiones por semana)
_TEACHERS = [
    ("García", "Matemáticas", 5),
    ("López", "Historia", 3),
    ("Ruiz", "Ciencias", 4),
    ("Díaz", "Inglés", 3),
]
_GROUPS = ["6A", "6B", "7A"]
_ROOMS = ["Aula 101", "Aula 102", "Laboratorio"]


def build_problem() -> SchedulingProblem:
    resources: list[Resource] = []
    rid = 0
    teacher_tag: dict[str, str] = {}
    for name, _subject, _n in _TEACHERS:
        tag = f"teacher#{rid}"
        teacher_tag[name] = tag
        resources.append(Resource(ResourceId(rid), name, frozenset({"teacher", tag})))
        rid += 1

    group_tag: dict[str, str] = {}
    for name in _GROUPS:
        tag = f"group#{rid}"
        group_tag[name] = tag
        resources.append(Resource(ResourceId(rid), name, frozenset({"group", tag})))
        rid += 1

    for i, name in enumerate(_ROOMS):
        rtype = "lab" if name == "Laboratorio" else "normal"
        resources.append(
            Resource(
                ResourceId(rid),
                name,
                frozenset({"room", f"room#{rid}", f"roomtype#{rtype}"}),
                attributes=(("seats", 30 + i * 5),),
            )
        )
        rid += 1

    tasks: list[Task] = []
    tid = 0
    for group in _GROUPS:
        for teacher, subject, sessions in _TEACHERS:
            for s in range(sessions):
                tasks.append(
                    Task(
                        TaskId(tid),
                        f"{subject} · {group}#{s}",
                        1,
                        (
                            ResourceRequirement(teacher_tag[teacher]),
                            ResourceRequirement(group_tag[group]),
                            ResourceRequirement("room"),
                        ),
                        attributes=(("size", 28),),
                    )
                )
                tid += 1

    grid = TimeGrid.from_segment_lengths([_PERIODS] * _DAYS)
    return SchedulingProblem(grid=grid, resources=tuple(resources), tasks=tuple(tasks))


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo.bjs")
    save_project(path, BjsProject.create("Colegio Demo", build_problem()))
    print(f"Proyecto de demostración escrito en: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
