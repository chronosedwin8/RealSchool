"""Métricas ampliadas para la comparación con Untis (O9, Actividad 10)."""

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
from scheduling_platform.core.assignment import Assignment
from scheduling_platform.core.ids import TimeSlotIndex
from scheduling_platform.core.solution import Solution
from scheduling_platform.engine import MetricsEngine
from scheduling_platform.engine.metrics import GapDistribution
from scheduling_platform.pipeline import OptimizationPipeline
from scheduling_platform.plugins import SchedulingModelContext, registry_with
from scheduling_platform.plugins.catalog.preferences import PreferEarlySlotsPlugin
from scheduling_platform.plugins.catalog.structural import ResourceNoOverlapPlugin
from scheduling_platform.sal import SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver


def _two_teacher_problem() -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([3]),
        resources=(
            Resource(ResourceId(0), "Prof A", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Prof B", frozenset({"teacher", "teacher#1"})),
            Resource(ResourceId(2), "Aula", frozenset({"room"})),
        ),
        tasks=(
            Task(
                TaskId(0), "A0", 1, (ResourceRequirement("teacher#0"), ResourceRequirement("room"))
            ),
            Task(
                TaskId(1), "A1", 1, (ResourceRequirement("teacher#0"), ResourceRequirement("room"))
            ),
        ),
    )


def test_gap_distribution_reparte_los_huecos() -> None:
    problem = _two_teacher_problem()
    # Prof A (id 0) con clases en 0 y 2 -> un hueco en 1; Prof B sin clases.
    solution = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(2))),
            Assignment(TaskId(1), TimeSlotIndex(2), (ResourceId(0), ResourceId(2))),
        ),
        objective_value=0,
    )
    dist = MetricsEngine().gap_distribution(problem, solution, tag="teacher")
    assert isinstance(dist, GapDistribution)
    assert dist.per_resource[0] == 1  # Prof A: un hueco
    assert dist.per_resource[1] == 0  # Prof B: sin huecos
    assert dist.maximum == 1
    assert dist.mean == 0.5  # (1 + 0) / 2
    assert dist.variance == 0.25
    assert dist.histogram == {0: 1, 1: 1}
    assert "huecos" in dist.render()


def test_gap_distribution_sin_recursos_del_tipo() -> None:
    problem = _two_teacher_problem()
    solution = Solution(assignments=(), objective_value=0)
    dist = MetricsEngine().gap_distribution(problem, solution, tag="inexistente")
    assert dist.per_resource == {}
    assert dist.mean == 0.0


def test_telemetria_registra_tiempo_a_primera_solucion() -> None:
    problem = _two_teacher_problem()
    context = SchedulingModelContext.build(problem, boolean_starts=True)
    registry = registry_with([ResourceNoOverlapPlugin(), PreferEarlySlotsPlugin(weight=1)])
    solver = ORToolsSolver()
    result = OptimizationPipeline().run(
        problem, registry.build_model(context), solver, SolverConfig(random_seed=1)
    )
    assert result.status is SolverStatus.OPTIMAL
    assert result.telemetry is not None
    # Hubo solución factible: el tiempo a la primera está registrado (>= 0 ms).
    assert result.telemetry.t_first_solution_ms >= 0
    assert "first_solution_ms" in solver.get_stats()
