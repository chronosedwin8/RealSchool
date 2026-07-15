"""Objetivo de calidad: estabilidad de aula por docente (Fase 12).

El motor no solo repara: mejora. Estas pruebas verifican que, con libertad para
reasignar aulas de un pool, el objetivo concentra a cada docente en menos aulas.
"""

from __future__ import annotations

from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.engine import SchedulingEngine
from scheduling_platform.plugins import SchedulingModelContext, registry_with
from scheduling_platform.plugins.catalog.quality import TeacherRoomStabilityPlugin
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.sal import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver

from .plugin_contract import assert_plugin_contract

_CONFIG = SolverConfig(random_seed=1, num_search_workers=2)


def _problem(n_classes: int, rooms: int, slots: int) -> SchedulingProblem:
    """Un docente y ``n_classes`` clases; ``rooms`` aulas equivalentes del pool."""
    resources = [Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"}))]
    resources.extend(
        Resource(ResourceId(1 + j), f"Aula {j}", frozenset({"room", "roompool#S"}))
        for j in range(rooms)
    )
    tasks = tuple(
        Task(
            TaskId(i),
            f"Clase {i}",
            1,
            (ResourceRequirement("teacher#0"), ResourceRequirement("roompool#S")),
        )
        for i in range(n_classes)
    )
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([slots]),
        resources=tuple(resources),
        tasks=tasks,
    )


def _rooms_used(problem: SchedulingProblem, result: object) -> int:
    room_ids = {int(r.id) for r in problem.resources if "room" in r.tags}
    usadas: set[int] = set()
    for a in result.solution.assignments:  # type: ignore[attr-defined]
        usadas.update(int(r) for r in a.resource_ids if int(r) in room_ids)
    return len(usadas)


def _solve(problem: SchedulingProblem, with_objective: bool) -> object:
    plugins: list[object] = [IntervalNoOverlapPlugin()]
    if with_objective:
        plugins.append(TeacherRoomStabilityPlugin(weight=1))
    engine = SchedulingEngine(
        registry=registry_with(plugins),  # type: ignore[arg-type]
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    return engine.solve(problem, _CONFIG)


def test_concentra_al_docente_en_una_sola_aula() -> None:
    # 3 clases del mismo docente, 3 aulas disponibles, 4 períodos.
    # Sin no-solape de aula lo obligan, así que podrían ir en 3 aulas distintas;
    # el objetivo debe concentrarlas en 1 (van en horas distintas por el docente).
    problem = _problem(n_classes=3, rooms=3, slots=4)
    result = _solve(problem, with_objective=True)
    assert result.solved  # type: ignore[attr-defined]
    assert _rooms_used(problem, result) == 1


def test_usa_mas_aulas_solo_cuando_hace_falta() -> None:
    # 3 clases pero solo 2 períodos: dos deben ir a la vez -> 2 aulas mínimo.
    problem = _problem(n_classes=3, rooms=3, slots=2)
    # (infactible para 1 docente: 3 clases en 2 períodos) -> usamos 2 docentes.
    resources = list(problem.resources)
    resources[0] = Resource(ResourceId(0), "Prof A", frozenset({"teacher", "teacher#0"}))
    resources.append(
        Resource(ResourceId(len(resources)), "Prof B", frozenset({"teacher", "teacher#1"}))
    )
    tasks = (
        Task(
            TaskId(0),
            "C0",
            1,
            (ResourceRequirement("teacher#0"), ResourceRequirement("roompool#S")),
        ),
        Task(
            TaskId(1),
            "C1",
            1,
            (ResourceRequirement("teacher#0"), ResourceRequirement("roompool#S")),
        ),
        Task(
            TaskId(2),
            "C2",
            1,
            (ResourceRequirement("teacher#1"), ResourceRequirement("roompool#S")),
        ),
    )
    problem = SchedulingProblem(grid=problem.grid, resources=tuple(resources), tasks=tasks)
    result = _solve(problem, with_objective=True)
    assert result.solved  # type: ignore[attr-defined]
    # docente 0 concentra sus 2 clases en 1 aula; el choque temporal con el
    # docente 1 obliga a una 2ª aula en ese período -> 2 aulas en total.
    assert _rooms_used(problem, result) == 2


def test_el_objetivo_cumple_el_contrato_de_plugin() -> None:
    context = SchedulingModelContext.build(_problem(2, 2, 4), boolean_starts=False)
    assert_plugin_contract(TeacherRoomStabilityPlugin(weight=2), context)
