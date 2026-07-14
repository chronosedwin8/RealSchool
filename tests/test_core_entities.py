"""Pruebas de entidades y value objects del núcleo (Fase 1)."""

from __future__ import annotations

import dataclasses

import pytest
from hypothesis import given

from scheduling_platform.core import (
    Assignment,
    Constraint,
    ConstraintId,
    ConstraintKind,
    HardConstraint,
    InvalidAssignment,
    InvalidEntity,
    Penalty,
    Resource,
    ResourceId,
    ResourceRequirement,
    SoftConstraint,
    Task,
    TaskId,
    TimeSlotIndex,
)

from .strategies import resources, tasks

# --- Resource -------------------------------------------------------------


def test_resource_valido() -> None:
    r = Resource(id=ResourceId(1), name="Aula 205", tags=frozenset({"room"}), capacity=2)
    assert r.is_unary is False
    assert r.has_tag("room") is True


def test_resource_capacidad_cero_lanza() -> None:
    with pytest.raises(InvalidEntity):
        Resource(id=ResourceId(1), name="X", capacity=0)


def test_resource_id_negativo_lanza() -> None:
    with pytest.raises(InvalidEntity):
        Resource(id=ResourceId(-1), name="X")


def test_resource_nombre_vacio_lanza() -> None:
    with pytest.raises(InvalidEntity):
        Resource(id=ResourceId(0), name="   ")


def test_resource_es_inmutable() -> None:
    r = Resource(id=ResourceId(0), name="X")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.name = "Y"  # type: ignore[misc]


@given(resources())
def test_property_resource_unario_sii_capacidad_uno(r: Resource) -> None:
    assert r.is_unary == (r.capacity == 1)


# --- ResourceRequirement --------------------------------------------------


def test_requirement_cantidad_cero_lanza() -> None:
    with pytest.raises(InvalidEntity):
        ResourceRequirement(tag="room", quantity=0)


def test_requirement_tag_vacio_lanza() -> None:
    with pytest.raises(InvalidEntity):
        ResourceRequirement(tag="")


# --- Task -----------------------------------------------------------------


def test_task_valida() -> None:
    t = Task(
        id=TaskId(1),
        name="Mate 7A",
        duration=2,
        requirements=(ResourceRequirement(tag="teacher"),),
    )
    assert t.duration == 2
    assert t.same_segment is True


def test_task_duracion_cero_lanza() -> None:
    with pytest.raises(InvalidEntity):
        Task(id=TaskId(0), name="X", duration=0, requirements=(ResourceRequirement(tag="t"),))


def test_task_sin_requerimientos_lanza() -> None:
    with pytest.raises(InvalidEntity):
        Task(id=TaskId(0), name="X", duration=1, requirements=())


@given(tasks())
def test_property_task_generada_es_valida(t: Task) -> None:
    assert t.duration >= 1
    assert len(t.requirements) >= 1


# --- Constraint -----------------------------------------------------------


def test_constraint_base_no_instanciable() -> None:
    with pytest.raises(TypeError):
        Constraint(id=ConstraintId(0), name="x")  # type: ignore[abstract]


def test_hard_constraint_kind() -> None:
    c = HardConstraint(id=ConstraintId(1), name="no_overlap")
    assert c.kind is ConstraintKind.HARD


def test_soft_constraint_kind_y_peso() -> None:
    c = SoftConstraint(id=ConstraintId(2), name="prefer_morning", weight=5)
    assert c.kind is ConstraintKind.SOFT
    assert c.weight == 5


def test_soft_constraint_peso_no_positivo_lanza() -> None:
    with pytest.raises(InvalidEntity):
        SoftConstraint(id=ConstraintId(2), name="x", weight=0)


# --- Assignment y Penalty -------------------------------------------------


def test_assignment_valida_y_calcula_fin() -> None:
    a = Assignment(task_id=TaskId(1), start=TimeSlotIndex(2), resource_ids=(ResourceId(3),))
    assert a.end(duration=2) == 4


def test_assignment_sin_recursos_lanza() -> None:
    with pytest.raises(InvalidAssignment):
        Assignment(task_id=TaskId(1), start=TimeSlotIndex(0), resource_ids=())


def test_penalty_negativa_lanza() -> None:
    with pytest.raises(InvalidAssignment):
        Penalty(source="gaps", amount=-1)


def test_penalty_origen_vacio_lanza() -> None:
    with pytest.raises(InvalidAssignment):
        Penalty(source="  ", amount=0)


def test_penalty_valida() -> None:
    p = Penalty(source="teacher_gaps", amount=7)
    assert p.amount == 7
