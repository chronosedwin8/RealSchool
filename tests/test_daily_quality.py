"""Reglas blandas de estructura diaria (SC-02/04/05/07/08).

Cada regla se prueba con un caso donde la penalización debe quedar en su mínimo
(el solver evita el defecto) y otro donde una restricción de horario la fuerza a
dispararse. Se resuelve con OR-Tools real a través del pipeline completo.
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
from scheduling_platform.core.ids import TimeSlotIndex
from scheduling_platform.pipeline import OptimizationPipeline, PipelineResult
from scheduling_platform.plugins import SchedulingModelContext, registry_with
from scheduling_platform.plugins.catalog.daily_quality import (
    DailySpanPlugin,
    SoftMaxConsecutivePlugin,
    TaskContinuityPlugin,
    TeacherGapsPlugin,
    WeeklyBalancePlugin,
)
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.sal import SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

from .plugin_contract import assert_plugin_contract

_CONFIG = SolverConfig(random_seed=1, num_search_workers=1)


def _teacher_problem(
    *, segments: list[int], n_classes: int, allowed: set[int] | None = None
) -> SchedulingProblem:
    starts = frozenset(TimeSlotIndex(s) for s in allowed) if allowed is not None else None
    resources = (
        Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
        Resource(ResourceId(1), "Aula", frozenset({"room"})),
    )
    tasks = tuple(
        Task(
            TaskId(i),
            f"Clase {i}",
            1,
            (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            allowed_starts=starts,
        )
        for i in range(n_classes)
    )
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths(segments), resources=resources, tasks=tasks
    )


def _group_problem(*, segments: list[int], n_classes: int, rooms: int = 2) -> SchedulingProblem:
    resources = [
        Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
        Resource(ResourceId(1), "Grupo", frozenset({"group", "group#0"})),
    ]
    resources.extend(
        Resource(ResourceId(2 + j), f"Aula {j}", frozenset({"room"})) for j in range(rooms)
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
        for i in range(n_classes)
    )
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths(segments), resources=tuple(resources), tasks=tasks
    )


def _solve(problem: SchedulingProblem, plugin: object) -> tuple[PipelineResult, ORToolsSolver]:
    context = SchedulingModelContext.build(problem, boolean_starts=True)
    registry = registry_with([IntervalNoOverlapPlugin(), plugin])  # type: ignore[list-item]
    solver = ORToolsSolver()
    result = OptimizationPipeline().run(problem, registry.build_model(context), solver, _CONFIG)
    return result, solver


# --- SC-02 huecos ---


def test_gaps_se_evitan_cuando_se_puede() -> None:
    # 2 clases en un día de 3 períodos: el solver las junta -> 0 huecos.
    problem = _teacher_problem(segments=[3], n_classes=2)
    result, solver = _solve(problem, TeacherGapsPlugin())
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 0


def test_gaps_se_penalizan_cuando_el_horario_los_fuerza() -> None:
    # 2 clases que solo pueden empezar en 0 o 2 -> forzosamente un hueco en 1.
    problem = _teacher_problem(segments=[3], n_classes=2, allowed={0, 2})
    result, solver = _solve(problem, TeacherGapsPlugin())
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 1


# --- SC-04 continuidad ---


def test_continuidad_prefiere_un_solo_bloque() -> None:
    problem = _group_problem(segments=[3], n_classes=2)
    result, solver = _solve(problem, TaskContinuityPlugin())
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 1  # un único bloque de clase


def test_continuidad_penaliza_la_fragmentacion_forzada() -> None:
    # clases que solo caben en 0 y 2 -> dos bloques separados.
    resources = [
        Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
        Resource(ResourceId(1), "Grupo", frozenset({"group", "group#0"})),
        Resource(ResourceId(2), "Aula", frozenset({"room"})),
    ]
    starts = frozenset({TimeSlotIndex(0), TimeSlotIndex(2)})
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
            allowed_starts=starts,
        )
        for i in range(2)
    )
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([3]), resources=tuple(resources), tasks=tasks
    )
    result, solver = _solve(problem, TaskContinuityPlugin())
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 2


# --- SC-05 balance semanal ---


def test_balance_reparte_entre_dias() -> None:
    # 2 clases del grupo, 2 días de 2 períodos: el pico baja a 1 (una por día).
    problem = _group_problem(segments=[2, 2], n_classes=2)
    result, solver = _solve(problem, WeeklyBalancePlugin())
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 1


# --- SC-07 jornada ---


def test_jornada_se_compacta() -> None:
    # 2 clases en un día de 3: jornada mínima = 2 períodos (adyacentes).
    problem = _teacher_problem(segments=[3], n_classes=2)
    result, solver = _solve(problem, DailySpanPlugin())
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 2


def test_jornada_larga_penaliza_mas() -> None:
    problem = _teacher_problem(segments=[3], n_classes=2, allowed={0, 2})
    result, solver = _solve(problem, DailySpanPlugin())
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 3  # del período 0 al 2


# --- SC-08 consecutivas (blanda) ---


def test_consecutivas_blandas_sin_exceso() -> None:
    # 2 clases en un día de 3, máx blando 2: cabe sin superar -> 0.
    problem = _teacher_problem(segments=[3], n_classes=2)
    result, solver = _solve(problem, SoftMaxConsecutivePlugin(limits=(("teacher", 2),)))
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 0


def test_consecutivas_blandas_penalizan_el_exceso() -> None:
    # 3 clases en un día de 3: fuerzan 3 seguidas -> excede el máx blando 2 en 1.
    problem = _teacher_problem(segments=[3], n_classes=3)
    result, solver = _solve(problem, SoftMaxConsecutivePlugin(limits=(("teacher", 2),)))
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 1


# --- Contrato del SDK ---


def test_reglas_blandas_diarias_cumplen_el_contrato() -> None:
    problem = _group_problem(segments=[2, 2], n_classes=2)
    context = SchedulingModelContext.build(problem, boolean_starts=True)
    for plugin in (
        TeacherGapsPlugin(),
        TaskContinuityPlugin(),
        WeeklyBalancePlugin(),
        DailySpanPlugin(),
        SoftMaxConsecutivePlugin(limits=(("teacher", 2),)),
    ):
        assert_plugin_contract(plugin, context)
