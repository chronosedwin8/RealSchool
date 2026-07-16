"""Ejemplo intermedio: estabilidad de aula (regla blanda) sobre un pool de aulas.

Un docente con tres clases y tres aulas equivalentes de un mismo *pool*. Con la
regla `teacher_room_stability` activa, el motor concentra al docente en las menos
aulas posibles.

    python docs/examples/intermediate/build.py   # crea intermediate.bjs
"""

from __future__ import annotations

from pathlib import Path

from scheduling_platform.application import new_project
from scheduling_platform.application.config import EngineConfig, PluginSetting, PluginsConfig
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
    """Crea un `.bjs` con la regla de estabilidad de aula configurada."""
    resources = [Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"}))]
    resources += [
        Resource(ResourceId(1 + j), f"Aula {j}", frozenset({"room", "roompool#S"}))
        for j in range(3)
    ]
    tasks = tuple(
        Task(
            TaskId(i),
            f"Clase {i}",
            1,
            (ResourceRequirement("teacher#0"), ResourceRequirement("roompool#S")),
        )
        for i in range(3)
    )
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([5]), resources=tuple(resources), tasks=tasks
    )
    constraints = PluginsConfig(
        (PluginSetting(id="teacher_room_stability", tier=2, weight=1),)
    )
    new_project(
        path,
        "Ejemplo intermedio",
        problem,
        constraints=constraints,
        solver_config=EngineConfig(max_time_seconds=10),
    )


if __name__ == "__main__":
    build("intermediate.bjs")
    print("intermediate.bjs creado")
