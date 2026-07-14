"""Formulación compacta con intervalos (Fase 11, ADR-015).

La prueba de rigor central: **differential testing** entre las dos
formulaciones del no-solape. La booleana (una variable de ocupación por
período) y la de intervalos (un intervalo opcional por par tarea-recurso) deben
producir exactamente el mismo espacio de soluciones y el mismo óptimo — pero la
segunda genera un modelo mucho más pequeño.
"""

from __future__ import annotations

import pytest

from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.engine import EngineResult, MetricsEngine, SchedulingEngine
from scheduling_platform.plugins import SchedulingModelContext, SchedulingPlugin, registry_with
from scheduling_platform.plugins.catalog.preferences import PreferEarlySlotsPlugin
from scheduling_platform.plugins.catalog.structural import (
    IntervalNoOverlapPlugin,
    ResourceNoOverlapPlugin,
)
from scheduling_platform.sal import FakeSolver, SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

_CONFIG = SolverConfig(random_seed=1, num_search_workers=1)


def _problem(
    n_classes: int = 3, slots: int = 4, rooms: int = 2, duration: int = 1
) -> SchedulingProblem:
    resources = [Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"}))]
    resources.extend(
        Resource(ResourceId(1 + j), f"Aula {j}", frozenset({"room"})) for j in range(rooms)
    )
    tasks = tuple(
        Task(
            TaskId(i),
            f"Clase {i}",
            duration,
            (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
        )
        for i in range(n_classes)
    )
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([slots]),
        resources=tuple(resources),
        tasks=tasks,
    )


def _solve(
    problem: SchedulingProblem, no_overlap: SchedulingPlugin, soft: bool = True
) -> EngineResult:
    plugins: list[SchedulingPlugin] = [no_overlap]
    if soft:
        plugins.append(PreferEarlySlotsPlugin(weight=1))
    engine = SchedulingEngine(registry=registry_with(plugins), solver_factory=ORToolsSolver)
    return engine.solve(problem, _CONFIG)


# --- Corrección de la formulación con intervalos ---


def test_intervalos_producen_horario_valido() -> None:
    problem = _problem(n_classes=3, slots=4)
    result = _solve(problem, IntervalNoOverlapPlugin())
    assert result.status is SolverStatus.OPTIMAL
    assert result.solved
    assert result.solution is not None
    # el docente no puede estar en dos sitios: slots distintos
    starts = [int(a.start) for a in result.solution.assignments]
    assert len(set(starts)) == 3


def test_intervalos_respetan_bloques_de_varios_periodos() -> None:
    # 2 clases de 2 períodos en un día de 4: solo caben pegadas (0-1 y 2-3)
    problem = _problem(n_classes=2, slots=4, duration=2)
    result = _solve(problem, IntervalNoOverlapPlugin(), soft=False)
    assert result.solved
    assert result.solution is not None
    starts = sorted(int(a.start) for a in result.solution.assignments)
    assert starts == [0, 2]


def test_intervalos_detectan_infactibilidad() -> None:
    # 5 clases para un docente en 4 períodos: imposible
    problem = _problem(n_classes=5, slots=4, rooms=3)
    result = _solve(problem, IntervalNoOverlapPlugin(), soft=False)
    assert result.solved is False


# --- Differential: ambas formulaciones son equivalentes ---


@pytest.mark.parametrize(
    ("n_classes", "slots", "rooms", "duration"),
    [
        (3, 4, 2, 1),
        (2, 4, 1, 2),
        (4, 5, 2, 1),
        (3, 6, 3, 2),
    ],
)
def test_differential_ambas_formulaciones_dan_el_mismo_optimo(
    n_classes: int, slots: int, rooms: int, duration: int
) -> None:
    problem = _problem(n_classes=n_classes, slots=slots, rooms=rooms, duration=duration)

    booleana = _solve(problem, ResourceNoOverlapPlugin())
    intervalos = _solve(problem, IntervalNoOverlapPlugin())

    # mismo veredicto de factibilidad
    assert booleana.solved == intervalos.solved
    if not booleana.solved:
        return
    assert booleana.solution is not None and intervalos.solution is not None

    # mismo valor óptimo de la función objetivo
    assert booleana.solution.objective_value == intervalos.solution.objective_value

    # ambos horarios superan la validación independiente
    metrics = MetricsEngine()
    assert metrics.compute(problem, booleana.solution).hard_violations == 0
    assert metrics.compute(problem, intervalos.solution).hard_violations == 0


def test_intervalos_generan_un_modelo_mucho_mas_pequeno() -> None:
    # Con un horizonte grande, la formulación booleana crece con los períodos y
    # la de intervalos no.
    problem = _problem(n_classes=6, slots=30, rooms=3)

    booleana = _solve(problem, ResourceNoOverlapPlugin(), soft=False)
    intervalos = _solve(problem, IntervalNoOverlapPlugin(), soft=False)

    t_bool = booleana.telemetry
    t_int = intervalos.telemetry
    assert t_bool is not None and t_int is not None

    # el modelo con intervalos es varias veces más pequeño
    assert t_int.num_variables < t_bool.num_variables / 3
    assert t_int.num_constraints < t_bool.num_constraints / 3


# --- La SAL recibe las llamadas correctas ---


def test_el_no_solape_llega_al_solver_como_intervalos() -> None:
    problem = _problem(n_classes=3, slots=4, rooms=2)
    context = SchedulingModelContext.build(problem)
    registry = registry_with([IntervalNoOverlapPlugin()])
    from scheduling_platform.pipeline import OptimizationPipeline

    solver = FakeSolver()
    solver.set_result(SolverStatus.OPTIMAL, {})
    OptimizationPipeline().run(problem, registry.build_model(context), solver)

    # un intervalo opcional por (tarea, recurso elegible); no-solape por recurso unario
    assert solver.intervals
    assert all(record.presence is not None for record in solver.intervals)
    assert solver.no_overlaps
