"""Ejemplo avanzado: varias reglas blandas compitiendo por Tiers.

Un grupo con seis clases en una semana de 5 × 4. Se combinan:
- `weekly_balance` (Tier 2): reparte las clases entre los días.
- `prefer_early_slots` (Tier 3): prefiere las primeras horas.

El Tier 2 domina al Tier 3: primero se equilibra la semana; entre las opciones
equilibradas, se eligen las horas más tempranas.

    python docs/examples/advanced/build.py   # crea advanced.bjs
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
    """Crea un `.bjs` con dos reglas blandas de Tiers distintos."""
    resources = (
        Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
        Resource(ResourceId(1), "Grupo", frozenset({"group", "group#0"})),
        Resource(ResourceId(2), "Aula A", frozenset({"room"})),
        Resource(ResourceId(3), "Aula B", frozenset({"room"})),
    )
    tasks = tuple(
        Task(
            TaskId(i),
            f"Clase {i}",
            1,
            (
                ResourceRequirement("teacher#0"),
                ResourceRequirement("group#0"),
                ResourceRequirement("room"),
            ),
        )
        for i in range(6)
    )
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4, 4, 4, 4, 4]), resources=resources, tasks=tasks
    )
    constraints = PluginsConfig(
        (
            PluginSetting(id="weekly_balance", tier=2, weight=2),
            PluginSetting(id="prefer_early_slots", tier=3, weight=1),
        )
    )
    new_project(
        path,
        "Ejemplo avanzado",
        problem,
        constraints=constraints,
        solver_config=EngineConfig(max_time_seconds=15),
    )


if __name__ == "__main__":
    build("advanced.bjs")
    print("advanced.bjs creado")
