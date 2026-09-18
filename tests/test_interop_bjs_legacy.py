"""Convertidor heredado `.bjs` -> `UntisProject` (solo lectura, un solo uso)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scheduling_platform.application.project import (
    BjsProject,
    LunchWindow,
    SchedulingOptions,
    SchoolPeriod,
    SchoolWeek,
    save_project,
)
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.core.assignment import Assignment as CanonAssignment
from scheduling_platform.core.ids import TimeSlotIndex
from scheduling_platform.core.solution import Penalty, Solution
from scheduling_platform.interop.bjs_legacy import (
    DEFAULT_GRID_ID,
    TIMETABLE_ID,
    load_bjs_as_project,
)
from scheduling_platform.interop.rsp import load_rsp, save_rsp
from scheduling_platform.untis_model import (
    Assignment,
    CriterionScore,
    Department,
    EntityKind,
    HalfDay,
    Lesson,
    LessonLine,
    MinMax,
    PeriodKind,
    Room,
    SchoolClass,
    TimeRequest,
    UntisProject,
)

_WEEK = 0  # índice de la semana lectiva "Primaria"


def _task(
    tid: int,
    name: str,
    tags: tuple[str, ...],
    *,
    duration: int = 1,
    **attrs: int,
) -> Task:
    return Task(
        TaskId(tid),
        name,
        duration,
        tuple(ResourceRequirement(t) for t in tags),
        attributes=tuple(attrs.items()),
    )


def _problem() -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4, 4]),
        resources=(
            Resource(ResourceId(0), "ANA", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "BEN", frozenset({"teacher", "teacher#1"})),
            Resource(
                ResourceId(2), "5A", frozenset({"group", "group#0"}), attributes=(("size", 25),)
            ),
            Resource(ResourceId(3), "5B", frozenset({"group", "group#1"})),
            Resource(
                ResourceId(4),
                "R1",
                frozenset({"room", "room#0", "roomtype#normal"}),
                attributes=(("seats", 30),),
            ),
            Resource(
                ResourceId(5),
                "R2",
                frozenset({"room", "room#1", "roomtype#normal"}),
                attributes=(("seats", 20),),
            ),
        ),
        tasks=(
            # Lección simple de 2 sesiones, aula del pool.
            _task(0, "Mate · g2#0", ("teacher#0", "group#0", "room"), size=25, school_week=_WEEK),
            _task(1, "Mate · g2#1", ("teacher#0", "group#0", "room"), size=25, school_week=_WEEK),
            # Acople: Inglés (5A, aula fija) y Francés (5B) a la vez.
            _task(
                2,
                "Ing · g2#0",
                ("teacher#0", "group#0", "room#0"),
                size=25,
                school_week=_WEEK,
                coupling=0,
                cseq=0,
            ),
            _task(
                3,
                "Fra · g3#0",
                ("teacher#1", "group#1", "room"),
                size=18,
                school_week=_WEEK,
                coupling=0,
                cseq=0,
            ),
            # Bloque doble sin semana lectiva asignada.
            _task(4, "Hist · g2#0", ("teacher#1", "group#0", "room"), duration=2, block=2),
        ),
    )


def _bjs() -> BjsProject:
    base = BjsProject.create("Colegio Demo", _problem())
    solution = Solution(
        assignments=(
            CanonAssignment(
                TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(2), ResourceId(4))
            ),
            CanonAssignment(
                TaskId(1), TimeSlotIndex(4), (ResourceId(0), ResourceId(2), ResourceId(5))
            ),
            CanonAssignment(
                TaskId(2), TimeSlotIndex(1), (ResourceId(0), ResourceId(2), ResourceId(4))
            ),
            CanonAssignment(
                TaskId(3), TimeSlotIndex(1), (ResourceId(1), ResourceId(3), ResourceId(5))
            ),
        ),
        objective_value=5,
        penalties=(Penalty("spread", 5),),
    )
    return replace(
        base,
        solution=solution,
        availability={0: ((0, 0), (1, 3))},
        lunch_window=LunchWindow(start=3, end=3, days=(0, 1)),
        subjects=("Mate", "Arte"),
        resource_info={
            0: {"full_name": "Ana Pérez", "email": "ana@example.org", "section": "CIE"},
            2: {"home_room": "R1", "section": "CIE"},
            4: {"alt_room": "R2"},
        },
        subject_info={"Mate": {"full_name": "Matemáticas", "color": "#f00"}},
        school_weeks=(
            SchoolWeek(
                name="Primaria",
                days=2,
                max_periods=4,
                afternoon_from=3,
                periods=(
                    SchoolPeriod("07:30", "08:15"),
                    SchoolPeriod("08:15", "09:00"),
                    SchoolPeriod("09:00", "09:20"),
                    SchoolPeriod("13:00", "13:45"),
                ),
                breaks=(2,),
            ),
        ),
        options=SchedulingOptions(avoid_same_subject_same_day=False),
    )


@pytest.fixture
def converted(tmp_path: Path) -> UntisProject:
    path = tmp_path / "demo.bjs"
    save_project(path, _bjs())
    return load_bjs_as_project(path)


def test_datos_maestros(converted: UntisProject) -> None:
    assert converted.school.name == "Colegio Demo"
    assert converted.departments == (Department("CIE"),)

    ana, ben = converted.teachers
    assert (ana.id, ana.name, ana.email, ana.department) == (
        "ANA",
        "Ana Pérez",
        "ana@example.org",
        "CIE",
    )
    assert ana.lunch_break == MinMax(1, None)
    assert ben.id == "BEN"

    assert converted.classes == (
        SchoolClass("5A", time_grid="Primaria", home_room="R1", department="CIE", students=25),
        SchoolClass("5B", time_grid="Primaria", students=18),
    )
    assert converted.rooms == (
        Room("R1", capacity=30, alternative_room="R2"),
        Room("R2", capacity=20),
    )
    materias = {s.id: s.name for s in converted.subjects}
    assert materias == {"Mate": "Matemáticas", "Ing": "", "Fra": "", "Hist": "", "Arte": ""}


def test_rejillas(converted: UntisProject) -> None:
    grids = converted.grid_by_id
    assert set(grids) == {"Primaria", DEFAULT_GRID_ID}
    primaria = grids["Primaria"]
    assert primaria.days == (1, 2)
    p1, _, p3, p4 = primaria.periods
    assert (p1.start, p1.end) == (7 * 60 + 30, 8 * 60 + 15)
    assert p3.kind is PeriodKind.BREAK
    assert p4.half_day is HalfDay.AFTERNOON
    assert [p.number for p in primaria.teaching_periods] == [1, 2, 4]
    assert len(grids[DEFAULT_GRID_ID].periods) == 4


def test_lecciones_y_acoples(converted: UntisProject) -> None:
    assert converted.lessons == (
        Lesson(1, (LessonLine("Mate", "ANA", ("5A",)),), 2, time_grid="Primaria"),
        Lesson(
            2,
            (
                LessonLine("Ing", "ANA", ("5A",), room="R1"),
                LessonLine("Fra", "BEN", ("5B",)),
            ),
            1,
            time_grid="Primaria",
        ),
        Lesson(
            3,
            (LessonLine("Hist", "BEN", ("5A",)),),
            2,
            time_grid=DEFAULT_GRID_ID,
            block=(2,),
            double_periods=MinMax(1, 1),
        ),
    )
    assert converted.lesson_by_number[2].is_coupled


def test_disponibilidad_como_deseos(converted: UntisProject) -> None:
    assert converted.time_requests == (
        TimeRequest(EntityKind.TEACHER, "ANA", -3, day=1, period=1),
        TimeRequest(EntityKind.TEACHER, "ANA", -3, day=2, period=4),
    )


def test_opciones_a_ponderacion(converted: UntisProject) -> None:
    assert converted.weighting.distribution_same_day == 0


def test_solucion_como_horario(converted: UntisProject) -> None:
    (tt,) = converted.timetables
    assert tt.id == TIMETABLE_ID
    assert set(tt.assignments) == {
        Assignment(1, 0, 1, 1, room="R1"),
        Assignment(1, 0, 2, 1, room="R2"),
        Assignment(2, 0, 1, 2, room="R1"),
        Assignment(2, 1, 1, 2, room="R2"),
    }
    assert tt.evaluation.unplaced_periods == 2  # el bloque doble de Historia
    assert tt.evaluation.scores == (CriterionScore("spread", 5, 1),)


def test_sin_semanas_ni_solucion(tmp_path: Path) -> None:
    path = tmp_path / "min.bjs"
    save_project(path, BjsProject.create("Min", _problem()))
    project = load_bjs_as_project(path)
    assert [g.id for g in project.time_grids] == [DEFAULT_GRID_ID]
    assert {c.time_grid for c in project.classes} == {DEFAULT_GRID_ID}
    assert project.timetables == ()
    assert project.time_requests == ()


def test_conversion_a_rsp(converted: UntisProject, tmp_path: Path) -> None:
    """El camino de migración completo: `.bjs` -> `UntisProject` -> `.rsp`."""
    path = tmp_path / "demo.rsp"
    save_rsp(converted, path)
    assert load_rsp(path) == converted
