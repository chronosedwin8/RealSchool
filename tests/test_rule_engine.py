"""Rule Engine: catálogo de reglas duras (Fase 8).

Cada regla se prueba con un caso positivo (se satisface), uno negativo (una
instancia que la fuerza a fallar produce INFEASIBLE) y, donde aplica, el de
frontera. Se resuelve con OR-Tools real a través del pipeline completo.
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
from scheduling_platform.pipeline import OptimizationPipeline, PipelineResult
from scheduling_platform.plugins import SchedulingModelContext, registry_with
from scheduling_platform.plugins.catalog.load import MaxConsecutivePlugin, MaxDailyLoadPlugin
from scheduling_platform.plugins.catalog.room import RoomCapacityPlugin
from scheduling_platform.plugins.catalog.structural import ResourceNoOverlapPlugin
from scheduling_platform.sal import SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

from .plugin_contract import assert_plugin_contract

_CONFIG = SolverConfig(random_seed=1, num_search_workers=1)


def _problem(
    *,
    segments: list[int],
    n_classes: int,
    task_size: int = 0,
    room_seats: int = 0,
    rooms: int = 1,
) -> SchedulingProblem:
    """Un docente (teacher#0), ``rooms`` aulas y ``n_classes`` clases de 1 período."""
    room_attrs = (("seats", room_seats),) if room_seats else ()
    task_attrs = (("size", task_size),) if task_size else ()
    resources = [
        Resource(ResourceId(0), "Prof. Juan", frozenset({"teacher", "teacher#0"})),
    ]
    resources.extend(
        Resource(ResourceId(1 + i), f"Aula {i}", frozenset({"room"}), attributes=room_attrs)
        for i in range(rooms)
    )
    tasks = tuple(
        Task(
            TaskId(i),
            f"Clase {i}",
            1,
            (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            attributes=task_attrs,
        )
        for i in range(n_classes)
    )
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths(segments),
        resources=tuple(resources),
        tasks=tasks,
    )


def _solve(problem: SchedulingProblem, plugins: list[object]) -> PipelineResult:
    context = SchedulingModelContext.build(problem)
    registry = registry_with([ResourceNoOverlapPlugin(), *plugins])  # type: ignore[list-item]
    model = registry.build_model(context)
    return OptimizationPipeline().run(problem, model, ORToolsSolver(), _CONFIG)


def _es_infactible(result: PipelineResult) -> bool:
    """El problema no tiene solución, la detecte el solver o el pipeline.

    Una regla dura puede volverse infactible por dos vías igual de válidas: el
    solver devuelve INFEASIBLE, o los pases del CIR detectan la contradicción
    estructural antes de resolver (y la explican).
    """
    if result.status is SolverStatus.INFEASIBLE:
        return True
    return result.stopped_before_solver and not result.report.feasible


# --- Máximo diario ---


def test_max_daily_load_permite_carga_repartida() -> None:
    # 3 clases, 2 días de 2 períodos, máximo 2/día -> factible (2 + 1)
    problem = _problem(segments=[2, 2], n_classes=3)
    result = _solve(problem, [MaxDailyLoadPlugin(limits=(("teacher", 2),))])
    assert result.status is SolverStatus.OPTIMAL


def test_max_daily_load_demasiado_estricto_es_infactible() -> None:
    # 3 clases, 2 días, máximo 1/día -> caben como mucho 2
    problem = _problem(segments=[2, 2], n_classes=3)
    assert _es_infactible(_solve(problem, [MaxDailyLoadPlugin(limits=(("teacher", 1),))]))


def test_max_daily_load_en_la_frontera_es_factible() -> None:
    # 4 clases, 2 días de 2 períodos, máximo 2/día -> exactamente en el límite
    problem = _problem(segments=[2, 2], n_classes=4)
    result = _solve(problem, [MaxDailyLoadPlugin(limits=(("teacher", 2),))])
    assert result.status is SolverStatus.OPTIMAL


# --- Máximo de períodos consecutivos ---


def test_max_consecutive_fuerza_un_hueco() -> None:
    # 3 clases en un día de 4 períodos con máximo 2 seguidos: hay solución
    # (p. ej. 0,1 _ 3), pero nunca 3 en fila.
    problem = _problem(segments=[4], n_classes=3)
    context = SchedulingModelContext.build(problem)
    registry = registry_with(
        [ResourceNoOverlapPlugin(), MaxConsecutivePlugin(limits=(("teacher", 2),))]
    )
    model = registry.build_model(context)
    solver = ORToolsSolver()
    result = OptimizationPipeline().run(problem, model, solver, _CONFIG)
    assert result.status is SolverStatus.OPTIMAL

    var_map = result.var_map
    assert var_map is not None
    ocupados = {
        slot
        for task in problem.tasks
        for slot in context.valid_starts(int(task.id))
        if solver.value(var_map[context.start_var(int(task.id), slot).key]) == 1
    }
    # ninguna ventana de 3 slots contiguos puede estar completamente ocupada
    for first in range(2):
        assert not {first, first + 1, first + 2} <= ocupados


def test_max_consecutive_demasiado_estricto_es_infactible() -> None:
    # 3 clases en un día de 3 períodos con máximo 2 seguidos: obligaría a
    # ocupar los 3 contiguos
    problem = _problem(segments=[3], n_classes=3)
    assert _es_infactible(_solve(problem, [MaxConsecutivePlugin(limits=(("teacher", 2),))]))


# --- Capacidad del aula ---


def test_room_capacity_permite_aula_suficiente() -> None:
    problem = _problem(segments=[3], n_classes=1, task_size=25, room_seats=30)
    result = _solve(problem, [RoomCapacityPlugin()])
    assert result.status is SolverStatus.OPTIMAL


def test_room_capacity_elige_el_aula_que_si_cabe() -> None:
    # dos aulas: solo la segunda (30 asientos) admite al grupo de 25
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([3]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula chica", frozenset({"room"}), attributes=(("seats", 10),)),
            Resource(
                ResourceId(2), "Aula grande", frozenset({"room"}), attributes=(("seats", 30),)
            ),
        ),
        tasks=(
            Task(
                TaskId(0),
                "Mate",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
                attributes=(("size", 25),),
            ),
        ),
    )
    context = SchedulingModelContext.build(problem)
    registry = registry_with([ResourceNoOverlapPlugin(), RoomCapacityPlugin()])
    solver = ORToolsSolver()
    result = OptimizationPipeline().run(problem, registry.build_model(context), solver, _CONFIG)
    assert result.status is SolverStatus.OPTIMAL
    var_map = result.var_map
    assert var_map is not None
    assert solver.value(var_map[context.assign_var(0, 1).key]) == 0  # aula chica descartada
    assert solver.value(var_map[context.assign_var(0, 2).key]) == 1  # aula grande elegida


def test_room_capacity_rechaza_aula_pequena_y_lo_explica() -> None:
    # grupo de 30 en la única aula de 20 asientos: no hay dónde ubicarlo. La
    # contradicción se detecta en los pases del CIR, antes de invocar al solver.
    problem = _problem(segments=[3], n_classes=1, task_size=30, room_seats=20)
    result = _solve(problem, [RoomCapacityPlugin()])
    assert _es_infactible(result)
    assert result.stopped_before_solver
    assert result.report.render()  # explicación accionable, no un INFEASIBLE mudo


def test_room_capacity_sin_atributos_no_aplica() -> None:
    problem = _problem(segments=[3], n_classes=1)  # sin size ni seats
    context = SchedulingModelContext.build(problem)
    assert RoomCapacityPlugin().contribute(context).constraints == ()


# --- Contrato del SDK ---


def test_reglas_duras_cumplen_el_contrato_de_plugin() -> None:
    problem = _problem(segments=[2, 2], n_classes=3, task_size=25, room_seats=30)
    context = SchedulingModelContext.build(problem)
    for plugin in (
        MaxDailyLoadPlugin(limits=(("teacher", 2),)),
        MaxConsecutivePlugin(limits=(("teacher", 2),)),
        RoomCapacityPlugin(),
    ):
        assert_plugin_contract(plugin, context)
