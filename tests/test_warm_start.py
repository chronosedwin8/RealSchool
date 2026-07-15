"""Warm start: sembrar la búsqueda con una solución conocida.

El caso real: el horario de un año tiene conflictos bajo no-solape estricto
(profesores en dos sitios por las clases combinadas del IB). Sembrando el motor
con él, CP-SAT lo **repara** manteniéndose cerca, en vez de reinventarlo.
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
from scheduling_platform.engine import SchedulingEngine, warm_start_hints
from scheduling_platform.plugins import SchedulingModelContext, registry_with
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.sal import FakeSolver, SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

_CONFIG = SolverConfig(random_seed=1, num_search_workers=2)


def _problem(n_classes: int = 3, slots: int = 4) -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([slots]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula 1", frozenset({"room"})),
            Resource(ResourceId(2), "Aula 2", frozenset({"room"})),
        ),
        tasks=tuple(
            Task(
                TaskId(i),
                f"Clase {i}",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            )
            for i in range(n_classes)
        ),
    )


# --- warm_start_hints ---


def test_hints_siembran_inicio_y_recursos() -> None:
    problem = _problem(n_classes=2, slots=4)
    context = SchedulingModelContext.build(problem, boolean_starts=False)
    solution = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(1), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(2), (ResourceId(0), ResourceId(2))),
        ),
        objective_value=0,
    )
    hints = warm_start_hints(context, solution)
    # inicio entero de cada tarea
    assert hints[context.task_start_var(0).key] == 1
    assert hints[context.task_start_var(1).key] == 2
    # recursos usados sembrados a 1
    assert hints[context.assign_var(0, 0).key] == 1
    assert hints[context.assign_var(0, 1).key] == 1
    assert hints[context.assign_var(1, 2).key] == 1


def test_los_hints_llegan_al_solver() -> None:
    problem = _problem(n_classes=1, slots=3)
    solution = Solution(
        assignments=(Assignment(TaskId(0), TimeSlotIndex(2), (ResourceId(0), ResourceId(1))),),
        objective_value=0,
    )
    solver = FakeSolver()
    # UNKNOWN: el motor no intenta extraer solución; solo comprobamos los hints,
    # que se aplican antes de resolver.
    solver.set_result(SolverStatus.UNKNOWN, {})
    engine = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin()]),
        solver_factory=lambda: solver,
        boolean_starts=False,
    )
    engine.solve(problem, _CONFIG, warm_start=solution)
    assert solver.hints  # el solver recibió sugerencias


# --- reparación end-to-end con OR-Tools ---


def test_warm_start_repara_un_horario_con_conflicto() -> None:
    # 3 clases del mismo docente; la "solución previa" pone dos en el mismo
    # período (conflicto). El motor, sembrado, debe repararlo a un horario válido.
    problem = _problem(n_classes=3, slots=4)
    conflictivo = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(0), (ResourceId(0), ResourceId(2))),  # choca
            Assignment(TaskId(2), TimeSlotIndex(1), (ResourceId(0), ResourceId(1))),
        ),
        objective_value=0,
    )
    engine = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin()]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    result = engine.solve(problem, _CONFIG, warm_start=conflictivo)
    assert result.solved
    assert result.solution is not None
    # el docente queda con sus 3 clases en períodos distintos
    starts = [int(a.start) for a in result.solution.assignments]
    assert len(set(starts)) == 3


def test_warm_start_con_solucion_valida_sigue_dando_horario_valido() -> None:
    # Sembrar con una solución ya válida no rompe nada: el motor devuelve un
    # horario válido. (El hint es orientación, no restricción: cuánto conserva
    # exactamente lo demuestran los años reales, no un caso de juguete.)
    problem = _problem(n_classes=3, slots=4)
    valido = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(1), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(2), TimeSlotIndex(2), (ResourceId(0), ResourceId(1))),
        ),
        objective_value=0,
    )
    engine = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin()]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    result = engine.solve(problem, _CONFIG, warm_start=valido)
    assert result.solved
    assert result.solution is not None
    starts = [int(a.start) for a in result.solution.assignments]
    assert len(set(starts)) == 3  # sin choques del docente
