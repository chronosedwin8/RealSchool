"""Estrategias de Hypothesis para generar problemas académicos válidos (Fase 2)."""

from __future__ import annotations

from hypothesis import strategies as st

from scheduling_platform.academic import (
    AcademicProblem,
    AssignmentId,
    GroupId,
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


@st.composite
def academic_problems(draw: st.DrawFn) -> AcademicProblem:
    """Problema académico válido y modesto (sin disponibilidad restringida).

    Las duraciones de sesión se acotan a ``periods_per_day`` para que toda
    tarea quepa en un día (``same_segment``), garantizando que el problema
    canónico resultante se construya sin infactibilidad estructural trivial.
    """
    num_days = draw(st.integers(min_value=1, max_value=5))
    periods_per_day = draw(st.integers(min_value=2, max_value=6))
    time_frame = TimeFrame(
        day_names=tuple(f"D{d}" for d in range(num_days)),
        periods_per_day=periods_per_day,
    )

    num_rooms = draw(st.integers(min_value=1, max_value=4))
    rooms = tuple(Room(id=RoomId(i), name=f"Aula{i}") for i in range(num_rooms))

    num_teachers = draw(st.integers(min_value=1, max_value=4))
    teachers = tuple(Teacher(id=TeacherId(i), name=f"Doc{i}") for i in range(num_teachers))

    num_groups = draw(st.integers(min_value=1, max_value=4))
    groups = tuple(StudentGroup(id=GroupId(i), name=f"Grupo{i}") for i in range(num_groups))

    num_subjects = draw(st.integers(min_value=1, max_value=4))
    subjects = tuple(Subject(id=SubjectId(i), name=f"Mat{i}") for i in range(num_subjects))

    num_assignments = draw(st.integers(min_value=1, max_value=6))
    session = st.integers(min_value=1, max_value=periods_per_day)
    assignments = tuple(
        TeachingAssignment(
            id=AssignmentId(i),
            teacher_id=TeacherId(draw(st.integers(min_value=0, max_value=num_teachers - 1))),
            subject_id=SubjectId(draw(st.integers(min_value=0, max_value=num_subjects - 1))),
            group_id=GroupId(draw(st.integers(min_value=0, max_value=num_groups - 1))),
            session_lengths=tuple(draw(st.lists(session, min_size=1, max_size=3))),
        )
        for i in range(num_assignments)
    )
    return AcademicProblem(
        time_frame=time_frame,
        rooms=rooms,
        teachers=teachers,
        groups=groups,
        subjects=subjects,
        assignments=assignments,
    )
