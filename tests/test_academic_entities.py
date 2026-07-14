"""Pruebas de entidades académicas y del marco horario (Fase 2)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scheduling_platform.academic import (
    AcademicIntegrityError,
    AcademicProblem,
    AssignmentId,
    GroupId,
    InvalidAcademicEntity,
    InvalidTimeFrame,
    Room,
    RoomId,
    StudentGroup,
    Subject,
    SubjectId,
    Teacher,
    TeacherId,
    TeachingAssignment,
    TimeFrame,
)

# --- TimeFrame ------------------------------------------------------------


def test_time_frame_to_grid_un_segmento_por_dia() -> None:
    tf = TimeFrame(day_names=("Lun", "Mar"), periods_per_day=4)
    grid = tf.to_grid()
    assert grid.horizon == 8
    assert len(grid.segments) == 2


def test_slot_of_y_decode_son_inversos() -> None:
    tf = TimeFrame(day_names=("Lun", "Mar", "Mie"), periods_per_day=5)
    slot = tf.slot_of(2, 3)
    assert slot == 2 * 5 + 3
    assert tf.decode(slot) == (2, 3)


@given(
    st.integers(min_value=1, max_value=6),
    st.integers(min_value=1, max_value=8),
)
def test_property_encode_decode_roundtrip(num_days: int, periods: int) -> None:
    tf = TimeFrame(day_names=tuple(f"D{d}" for d in range(num_days)), periods_per_day=periods)
    for day in range(num_days):
        for period in range(periods):
            assert tf.decode(tf.slot_of(day, period)) == (day, period)


def test_time_frame_periodos_cero_lanza() -> None:
    with pytest.raises(InvalidTimeFrame):
        TimeFrame(day_names=("Lun",), periods_per_day=0)


def test_slot_of_fuera_de_rango_lanza() -> None:
    tf = TimeFrame(day_names=("Lun",), periods_per_day=3)
    with pytest.raises(InvalidTimeFrame):
        tf.slot_of(0, 5)


# --- Entidades ------------------------------------------------------------


def test_room_valida_y_defaults() -> None:
    r = Room(id=RoomId(0), name="Lab A", capacity=30, room_type="lab", equipment=frozenset({"pc"}))
    assert r.room_type == "lab"
    assert "pc" in r.equipment


def test_room_capacidad_cero_lanza() -> None:
    with pytest.raises(InvalidAcademicEntity):
        Room(id=RoomId(0), name="X", capacity=0)


def test_teacher_disponibilidad_opcional() -> None:
    t = Teacher(id=TeacherId(0), name="Juan", available_periods=frozenset({(0, 0), (0, 1)}))
    assert t.available_periods is not None


def test_group_size_cero_lanza() -> None:
    with pytest.raises(InvalidAcademicEntity):
        StudentGroup(id=GroupId(0), name="7A", size=0)


def test_teaching_assignment_sin_sesiones_lanza() -> None:
    with pytest.raises(InvalidAcademicEntity):
        TeachingAssignment(
            id=AssignmentId(0),
            teacher_id=TeacherId(0),
            subject_id=SubjectId(0),
            group_id=GroupId(0),
            session_lengths=(),
        )


def test_teaching_assignment_sesion_cero_lanza() -> None:
    with pytest.raises(InvalidAcademicEntity):
        TeachingAssignment(
            id=AssignmentId(0),
            teacher_id=TeacherId(0),
            subject_id=SubjectId(0),
            group_id=GroupId(0),
            session_lengths=(2, 0),
        )


# --- Agregado -------------------------------------------------------------


def _one_of_each() -> dict[str, object]:
    return {
        "time_frame": TimeFrame(day_names=("Lun",), periods_per_day=4),
        "rooms": (Room(RoomId(0), "Aula"),),
        "teachers": (Teacher(TeacherId(0), "Juan"),),
        "groups": (StudentGroup(GroupId(0), "7A"),),
        "subjects": (Subject(SubjectId(0), "Mate"),),
    }


def test_carga_con_docente_inexistente_lanza() -> None:
    base = _one_of_each()
    with pytest.raises(AcademicIntegrityError):
        AcademicProblem(
            time_frame=base["time_frame"],  # type: ignore[arg-type]
            rooms=base["rooms"],  # type: ignore[arg-type]
            teachers=base["teachers"],  # type: ignore[arg-type]
            groups=base["groups"],  # type: ignore[arg-type]
            subjects=base["subjects"],  # type: ignore[arg-type]
            assignments=(
                TeachingAssignment(
                    id=AssignmentId(0),
                    teacher_id=TeacherId(99),  # inexistente
                    subject_id=SubjectId(0),
                    group_id=GroupId(0),
                    session_lengths=(1,),
                ),
            ),
        )


def test_accesores_by_id_devuelven_entidad_o_lanzan() -> None:
    problem = AcademicProblem(
        time_frame=TimeFrame(day_names=("Lun",), periods_per_day=4),
        rooms=(Room(RoomId(0), "Aula", equipment=frozenset({"proyector"})),),
        teachers=(Teacher(TeacherId(0), "Juan"),),
        groups=(StudentGroup(GroupId(0), "7A"),),
        subjects=(Subject(SubjectId(0), "Mate"),),
        assignments=(
            TeachingAssignment(AssignmentId(0), TeacherId(0), SubjectId(0), GroupId(0), (1,)),
        ),
    )
    assert problem.room_by_id(RoomId(0)).name == "Aula"
    assert problem.teacher_by_id(TeacherId(0)).name == "Juan"
    assert problem.group_by_id(GroupId(0)).name == "7A"
    assert problem.subject_by_id(SubjectId(0)).name == "Mate"
    assert problem.assignment_by_id(AssignmentId(0)).teacher_id == TeacherId(0)
    for lookup in (
        lambda: problem.room_by_id(RoomId(9)),
        lambda: problem.teacher_by_id(TeacherId(9)),
        lambda: problem.group_by_id(GroupId(9)),
        lambda: problem.subject_by_id(SubjectId(9)),
        lambda: problem.assignment_by_id(AssignmentId(9)),
    ):
        with pytest.raises(AcademicIntegrityError):
            lookup()


def test_equipamiento_del_aula_produce_tag() -> None:
    from scheduling_platform.academic import AcademicToCanonicalAdapter
    from scheduling_platform.academic.tags import equipment_tag

    problem = AcademicProblem(
        time_frame=TimeFrame(day_names=("Lun",), periods_per_day=4),
        rooms=(Room(RoomId(0), "Lab", room_type="lab", equipment=frozenset({"microscopio"})),),
        teachers=(Teacher(TeacherId(0), "Juan"),),
        groups=(StudentGroup(GroupId(0), "7A"),),
        subjects=(Subject(SubjectId(0), "Bio"),),
        assignments=(
            TeachingAssignment(AssignmentId(0), TeacherId(0), SubjectId(0), GroupId(0), (1,)),
        ),
    )
    translation = AcademicToCanonicalAdapter().translate(problem)
    room_res = next(r for r in translation.problem.resources if "room" in r.tags)
    assert equipment_tag("microscopio") in room_res.tags


def test_ids_de_docente_duplicados_lanza() -> None:
    base = _one_of_each()
    with pytest.raises(AcademicIntegrityError):
        AcademicProblem(
            time_frame=base["time_frame"],  # type: ignore[arg-type]
            rooms=base["rooms"],  # type: ignore[arg-type]
            teachers=(Teacher(TeacherId(0), "A"), Teacher(TeacherId(0), "B")),
            groups=base["groups"],  # type: ignore[arg-type]
            subjects=base["subjects"],  # type: ignore[arg-type]
            assignments=(
                TeachingAssignment(
                    id=AssignmentId(0),
                    teacher_id=TeacherId(0),
                    subject_id=SubjectId(0),
                    group_id=GroupId(0),
                    session_lengths=(1,),
                ),
            ),
        )
