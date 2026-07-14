"""Pruebas del agregado SchedulingProblem y de Solution.validate_against (Fase 1)."""

from __future__ import annotations

import pytest

from scheduling_platform.core import (
    Assignment,
    InvalidAssignment,
    ReferentialIntegrityError,
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


def _mini_problem() -> SchedulingProblem:
    """Mini-problema canónico: 2 recursos, 3 tareas, rejilla 6 slots en 2 segmentos."""
    grid = TimeGrid.from_segment_lengths([3, 3])
    resources = (
        Resource(id=ResourceId(0), name="Prof. Juan", tags=frozenset({"teacher"})),
        Resource(id=ResourceId(1), name="Aula 205", tags=frozenset({"room"})),
    )
    tasks = (
        Task(TaskId(0), "Mate", 2, (ResourceRequirement("teacher"), ResourceRequirement("room"))),
        Task(TaskId(1), "Física", 1, (ResourceRequirement("teacher"),)),
        Task(TaskId(2), "Historia", 1, (ResourceRequirement("room"),)),
    )
    return SchedulingProblem(grid=grid, resources=resources, tasks=tasks)


def test_mini_problema_valido_se_construye() -> None:
    problem = _mini_problem()
    assert problem.horizon == 6
    assert problem.resource_by_id(ResourceId(0)).name == "Prof. Juan"
    assert problem.task_by_id(TaskId(1)).duration == 1


def test_ids_de_recurso_duplicados_lanza() -> None:
    grid = TimeGrid.from_segment_lengths([4])
    with pytest.raises(ReferentialIntegrityError):
        SchedulingProblem(
            grid=grid,
            resources=(
                Resource(ResourceId(0), "A"),
                Resource(ResourceId(0), "B"),  # id duplicado
            ),
            tasks=(Task(TaskId(0), "T", 1, (ResourceRequirement("x"),)),),
        )


def test_tarea_que_no_cabe_lanza() -> None:
    grid = TimeGrid.from_segment_lengths(
        [2, 2]
    )  # ningún segmento admite duración 3 con same_segment
    with pytest.raises(ReferentialIntegrityError):
        SchedulingProblem(
            grid=grid,
            resources=(Resource(ResourceId(0), "A", frozenset({"x"})),),
            tasks=(Task(TaskId(0), "T", 3, (ResourceRequirement("x"),), same_segment=True),),
        )


def test_allowed_starts_fuera_de_rejilla_lanza() -> None:
    grid = TimeGrid.from_segment_lengths([4])
    with pytest.raises(ReferentialIntegrityError):
        SchedulingProblem(
            grid=grid,
            resources=(Resource(ResourceId(0), "A", frozenset({"x"})),),
            tasks=(
                Task(
                    TaskId(0),
                    "T",
                    2,
                    (ResourceRequirement("x"),),
                    allowed_starts=frozenset({TimeSlotIndex(10)}),  # fuera del horizonte
                ),
            ),
        )


def test_valid_starts_for_intersecta_dominio_permitido() -> None:
    grid = TimeGrid.from_segment_lengths([4])
    task = Task(
        TaskId(0),
        "T",
        2,
        (ResourceRequirement("x"),),
        allowed_starts=frozenset({TimeSlotIndex(0), TimeSlotIndex(2)}),
    )
    problem = SchedulingProblem(
        grid=grid,
        resources=(Resource(ResourceId(0), "A", frozenset({"x"})),),
        tasks=(task,),
    )
    assert problem.valid_starts_for(task) == frozenset({TimeSlotIndex(0), TimeSlotIndex(2)})


# --- Solution.validate_against -------------------------------------------


def test_solucion_valida_pasa_validacion() -> None:
    problem = _mini_problem()
    solution = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(2), (ResourceId(0),)),
            Assignment(TaskId(2), TimeSlotIndex(0), (ResourceId(1),)),
        ),
        objective_value=0,
    )
    solution.validate_against(problem)  # no lanza


def test_solucion_con_tarea_faltante_lanza() -> None:
    problem = _mini_problem()
    solution = Solution(
        assignments=(Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0),)),),
        objective_value=0,
    )
    with pytest.raises(ReferentialIntegrityError):
        solution.validate_against(problem)


def test_solucion_con_recurso_inexistente_lanza() -> None:
    problem = _mini_problem()
    solution = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(99),)),  # recurso inexistente
            Assignment(TaskId(1), TimeSlotIndex(2), (ResourceId(0),)),
            Assignment(TaskId(2), TimeSlotIndex(0), (ResourceId(1),)),
        ),
        objective_value=0,
    )
    with pytest.raises(ReferentialIntegrityError):
        solution.validate_against(problem)


def test_solucion_con_inicio_invalido_lanza() -> None:
    problem = _mini_problem()
    # La tarea 0 dura 2 con same_segment: start=2 cruzaría la frontera [0,1,2|3,4,5] -> inválido
    solution = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(2), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(0), (ResourceId(0),)),
            Assignment(TaskId(2), TimeSlotIndex(0), (ResourceId(1),)),
        ),
        objective_value=0,
    )
    with pytest.raises(InvalidAssignment):
        solution.validate_against(problem)


def test_assignment_for_devuelve_none_si_no_existe() -> None:
    solution = Solution(
        assignments=(Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0),)),),
        objective_value=0,
    )
    assert solution.assignment_for(TaskId(0)) is not None
    assert solution.assignment_for(TaskId(99)) is None


def test_solucion_objetivo_negativo_lanza() -> None:
    with pytest.raises(InvalidAssignment):
        Solution(
            assignments=(Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0),)),),
            objective_value=-1,
        )


def test_dos_asignaciones_para_una_tarea_lanza() -> None:
    with pytest.raises(InvalidAssignment):
        Solution(
            assignments=(
                Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0),)),
                Assignment(TaskId(0), TimeSlotIndex(1), (ResourceId(0),)),
            ),
            objective_value=0,
        )
