"""Catálogo de instancias infactibles y su detección estructural (Fase 5).

Cada categoría de conflicto tiene una instancia diseñada; se verifica que el
Graph Builder la detecta y produce un mensaje accionable (nunca un INFEASIBLE
mudo). También se verifica que una instancia factible no genera hallazgos.
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
    TimeSlotIndex,
)
from scheduling_platform.pipeline import ConstraintGraphBuilder


def _grid(segments: list[int]) -> TimeGrid:
    return TimeGrid.from_segment_lengths(segments)


def test_detecta_tag_sin_proveedor() -> None:
    problem = SchedulingProblem(
        grid=_grid([4]),
        resources=(Resource(ResourceId(0), "Aula", frozenset({"room"})),),
        tasks=(
            Task(TaskId(0), "Química", 1, (ResourceRequirement("lab"),)),  # nadie provee 'lab'
        ),
    )
    issues = ConstraintGraphBuilder().analyze(problem)
    kinds = {i.kind for i in issues}
    assert "unsatisfiable_requirement" in kinds
    assert any("lab" in i.message for i in issues)


def test_detecta_dominio_temporal_vacio() -> None:
    # Tarea de duración 3 con same_segment en segmentos de 2: no cabe -> el
    # agregado ya lo rechaza; usamos allowed_starts vacío por disponibilidad.
    task = Task(
        TaskId(0),
        "Mate",
        1,
        (ResourceRequirement("teacher"),),
        allowed_starts=frozenset(),  # sin ningún horario permitido
    )
    problem = SchedulingProblem(
        grid=_grid([4]),
        resources=(Resource(ResourceId(0), "Prof", frozenset({"teacher"})),),
        tasks=(task,),
    )
    issues = ConstraintGraphBuilder().analyze(problem)
    assert any(i.kind == "empty_time_domain" for i in issues)


def test_detecta_sobre_suscripcion_de_docente() -> None:
    # Prof. Juan solo puede en 2 slots ({0,1}) pero debe impartir 3 períodos.
    disponibles = frozenset({TimeSlotIndex(0), TimeSlotIndex(1)})
    tasks = tuple(
        Task(
            TaskId(i),
            f"Clase {i}",
            1,
            (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            allowed_starts=disponibles,
        )
        for i in range(3)
    )
    problem = SchedulingProblem(
        grid=_grid([4]),
        resources=(
            Resource(ResourceId(0), "Prof. Juan", frozenset({"teacher", "teacher#0"})),
            # dos aulas para que 'room' sea multi-proveedor y no se marque
            Resource(ResourceId(1), "Aula 1", frozenset({"room"})),
            Resource(ResourceId(2), "Aula 2", frozenset({"room"})),
        ),
        tasks=tasks,
    )
    issues = ConstraintGraphBuilder().analyze(problem)
    oversub = [i for i in issues if i.kind == "resource_oversubscription"]
    assert len(oversub) == 1
    assert "Prof. Juan" in oversub[0].message
    assert "Faltan 1" in oversub[0].message


def test_detecta_demanda_global_supera_oferta() -> None:
    # 3 aulas, horizonte 2 -> oferta 'room' = 6; demanda = 7 clases de 1 -> infactible.
    tasks = tuple(
        Task(TaskId(i), f"Clase {i}", 1, (ResourceRequirement("room"),)) for i in range(7)
    )
    problem = SchedulingProblem(
        grid=_grid([2]),
        resources=tuple(
            Resource(ResourceId(i), f"Aula {i}", frozenset({"room"})) for i in range(3)
        ),
        tasks=tasks,
    )
    issues = ConstraintGraphBuilder().analyze(problem)
    globales = [i for i in issues if i.kind == "global_capacity"]
    assert len(globales) == 1
    assert "supera la oferta" in globales[0].message


def test_instancia_factible_no_genera_hallazgos() -> None:
    problem = SchedulingProblem(
        grid=_grid([4]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula", frozenset({"room"})),
            Resource(ResourceId(2), "Aula 2", frozenset({"room"})),
        ),
        tasks=(
            Task(
                TaskId(0),
                "Mate",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            ),
        ),
    )
    assert ConstraintGraphBuilder().analyze(problem) == ()
