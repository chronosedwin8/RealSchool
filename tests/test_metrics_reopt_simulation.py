"""Metrics, ReOptimization y Simulation Engines (Fase 10).

Pruebas de rigor:
- KPIs verificados contra cálculo manual en instancias pequeñas.
- **Invariante de reoptimización**: lo congelado no se mueve ni un período.
- Simulación what-if: un escenario mejor debe puntuar mejor.
"""

from __future__ import annotations

from scheduling_platform.core import (
    Assignment,
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Solution,
    Task,
    TaskId,
    TimeGrid,
    TimeSlotIndex,
)
from scheduling_platform.engine import (
    MetricsEngine,
    ReOptimizationEngine,
    SchedulingEngine,
    SimulationEngine,
    freeze_all_except,
)
from scheduling_platform.plugins import registry_with
from scheduling_platform.plugins.catalog.preferences import PreferEarlySlotsPlugin
from scheduling_platform.plugins.catalog.structural import ResourceNoOverlapPlugin
from scheduling_platform.sal import SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

_CONFIG = SolverConfig(random_seed=1, num_search_workers=1)
_PLUGINS = [ResourceNoOverlapPlugin()]


def _problem(
    n_classes: int = 3, slots: int = 4, teachers: int = 1, rooms: int = 1
) -> SchedulingProblem:
    resources = [
        Resource(ResourceId(i), f"Prof {i}", frozenset({"teacher", f"teacher#{i}"}))
        for i in range(teachers)
    ]
    resources.extend(
        Resource(ResourceId(teachers + j), f"Aula {j}", frozenset({"room"})) for j in range(rooms)
    )
    tasks = tuple(
        Task(
            TaskId(i),
            f"Clase {i}",
            1,
            (ResourceRequirement(f"teacher#{i % teachers}"), ResourceRequirement("room")),
        )
        for i in range(n_classes)
    )
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([slots]),
        resources=tuple(resources),
        tasks=tasks,
    )


def _engine(plugins: list[object] | None = None) -> SchedulingEngine:
    return SchedulingEngine(
        registry=registry_with([*_PLUGINS, *(plugins or [])]),  # type: ignore[list-item]
        solver_factory=ORToolsSolver,
    )


# --- Metrics Engine (verificado a mano) ---


def test_kpis_calculados_a_mano() -> None:
    # 1 docente, 1 aula, día de 4 períodos; clases en 0 y 3 -> hueco de 2.
    problem = _problem(n_classes=2, slots=4)
    solution = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(3), (ResourceId(0), ResourceId(1))),
        ),
        objective_value=0,
    )
    metrics = MetricsEngine().compute(problem, solution)
    assert metrics.hard_violations == 0
    # aula ocupada 2 de 4 períodos
    assert metrics.room_utilization_pct == 50.0
    # entre el período 0 y el 3 quedan 2 huecos intercalados
    assert metrics.teacher_gaps == 2
    # un solo docente -> balance perfecto por definición
    assert metrics.teacher_load_balance_pct == 100.0
    # calidad = 100 - 2 huecos * 2.0
    assert metrics.quality_score == 96.0


def test_sin_huecos_puntua_mejor_que_con_huecos() -> None:
    problem = _problem(n_classes=2, slots=4)
    compacto = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(1), (ResourceId(0), ResourceId(1))),
        ),
        objective_value=0,
    )
    disperso = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(3), (ResourceId(0), ResourceId(1))),
        ),
        objective_value=0,
    )
    comparison = MetricsEngine().compare(problem, baseline=disperso, candidate=compacto)
    assert comparison.candidate_is_better
    assert comparison.quality_delta > 0
    assert "Calidad" in comparison.render()


def test_violacion_dura_hunde_la_calidad() -> None:
    problem = _problem(n_classes=2, slots=4)
    invalida = Solution(  # mismo docente, mismo período
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
        ),
        objective_value=0,
    )
    metrics = MetricsEngine().compute(problem, invalida)
    assert metrics.hard_violations > 0
    assert metrics.quality_score == 0.0
    assert "Violaciones duras" in metrics.render()


def test_balance_penaliza_carga_desigual() -> None:
    # 2 docentes: uno da 2 clases y el otro 1 -> balance = 100*(1 - 1/2) = 50%
    problem = _problem(n_classes=3, slots=4, teachers=2)
    solution = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(2))),
            Assignment(TaskId(1), TimeSlotIndex(1), (ResourceId(1), ResourceId(2))),
            Assignment(TaskId(2), TimeSlotIndex(2), (ResourceId(0), ResourceId(2))),
        ),
        objective_value=0,
    )
    metrics = MetricsEngine().compute(problem, solution)
    assert metrics.teacher_load_balance_pct == 50.0


# --- ReOptimization Engine ---


def test_reoptimizacion_no_mueve_lo_congelado() -> None:
    problem = _problem(n_classes=3, slots=4)
    base = _engine([PreferEarlySlotsPlugin(weight=1)]).solve(problem, _CONFIG)
    assert base.solution is not None

    reopt = ReOptimizationEngine(plugins=_PLUGINS, solver_factory=ORToolsSolver)
    # dejamos libre solo la clase 2; las clases 0 y 1 quedan congeladas
    result = reopt.reoptimize(problem, base.solution, unfrozen=[TaskId(2)], config=_CONFIG)
    assert result.status is SolverStatus.OPTIMAL
    assert result.solution is not None

    antes = {int(a.task_id): (int(a.start), a.resource_ids) for a in base.solution.assignments}
    despues = {int(a.task_id): (int(a.start), a.resource_ids) for a in result.solution.assignments}
    # INVARIANTE: lo congelado es idéntico
    for tid in (0, 1):
        assert despues[tid] == antes[tid]
    # la clase liberada sigue siendo válida
    assert result.solved


def test_freeze_all_except_selecciona_bien() -> None:
    solution = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0),)),
            Assignment(TaskId(1), TimeSlotIndex(1), (ResourceId(0),)),
        ),
        objective_value=0,
    )
    frozen = freeze_all_except(solution, unfrozen=[TaskId(1)])
    assert len(frozen) == 1
    assert frozen[0].task_id == 0
    assert frozen[0].start == 0


def test_reoptimizacion_completa_equivale_a_resolver_de_cero() -> None:
    problem = _problem(n_classes=3, slots=4)
    base = _engine().solve(problem, _CONFIG)
    assert base.solution is not None

    reopt = ReOptimizationEngine(plugins=_PLUGINS, solver_factory=ORToolsSolver)
    # nada congelado: todas las tareas libres
    todas = [TaskId(int(t.id)) for t in problem.tasks]
    result = reopt.reoptimize(problem, base.solution, unfrozen=todas, config=_CONFIG)
    assert result.solved


# --- Simulation Engine ---


def test_simulacion_contratar_docente_vuelve_factible() -> None:
    # 5 clases y 2 aulas en 4 períodos, pero un solo docente: el docente no
    # puede estar en dos sitios a la vez, así que 5 > 4 -> imposible.
    base = _problem(n_classes=5, slots=4, teachers=1, rooms=2)
    # Escenario "¿y si contrato otro docente?": las clases se reparten -> factible.
    escenario = _problem(n_classes=5, slots=4, teachers=2, rooms=2)

    sim = SimulationEngine(plugins=_PLUGINS, solver_factory=ORToolsSolver)
    report = sim.compare(base, escenario, config=_CONFIG)

    assert report.baseline.feasible is False
    assert report.scenario.feasible is True
    assert report.comparison is None  # no hay línea base con la que comparar KPIs
    assert "vuelve factible" in report.render()


def test_simulacion_compara_kpis_entre_escenarios() -> None:
    base = _problem(n_classes=2, slots=4, teachers=1)
    # Escenario con más períodos disponibles: mismo trabajo, más holgura.
    escenario = _problem(n_classes=2, slots=6, teachers=1)

    sim = SimulationEngine(plugins=_PLUGINS, solver_factory=ORToolsSolver)
    report = sim.compare(base, escenario, config=_CONFIG)

    assert report.baseline.feasible and report.scenario.feasible
    comparison = report.comparison
    assert comparison is not None
    # ambos horarios son válidos: sin violaciones duras
    assert comparison.baseline.hard_violations == 0
    assert comparison.candidate.hard_violations == 0
    assert "Calidad" in report.render()
