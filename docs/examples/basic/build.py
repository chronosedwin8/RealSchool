"""Ejemplo básico: un docente, un aula, cinco clases en una semana.

    python docs/examples/basic/build.py   # crea basic.bjs
"""

from __future__ import annotations

from pathlib import Path

from scheduling_platform.application import new_project
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)


def build(path: str | Path) -> None:
    """Crea un `.bjs` con un problema mínimo factible."""
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([5, 5, 5, 5, 5]),  # 5 días × 5 períodos
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula", frozenset({"room"})),
        ),
        tasks=tuple(
            Task(
                TaskId(i),
                f"Clase {i}",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            )
            for i in range(5)
        ),
    )
    new_project(path, "Ejemplo básico", problem)


if __name__ == "__main__":
    build("basic.bjs")
    print("basic.bjs creado")
