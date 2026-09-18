"""Modelo de dominio Untis: la capa pública de datos de RealSchool.

Sustituye a `academic/`. Replica el modelo mental de Untis —datos maestros,
lecciones con acoples explícitos, deseos -3…+3 y ponderaciones 0-5— sin depender
del motor: nada aquí importa `core`. El único traductor al modelo canónico es
`scheduling_platform.bridge` (ver `REFACTOR_UNTIS_MAESTRO.md`, secciones 4 y 5).
"""

from .common import (
    REQUEST_MAX,
    REQUEST_MIN,
    UNSET,
    EntityKind,
    HalfDay,
    MinMax,
    PeriodKind,
)
from .diagnostics import DataIssue, Severity, diagnose_data
from .lessons import (
    LINES_PER_LESSON,
    Lesson,
    LessonLine,
    build_lesson_id,
    double_periods_from_block,
    split_lesson_id,
)
from .master_data import (
    DateScheme,
    Department,
    Room,
    SchoolClass,
    StudentGroup,
    Subject,
    Teacher,
    Term,
)
from .project import SchoolInfo, UntisProject
from .requests import TimeRequest, UnspecifiedKind, UnspecifiedRequest
from .time_grid import PeriodDef, TimeGrid, hhmm_to_minutes, minutes_to_hhmm
from .timetable import Assignment, CriterionScore, Evaluation, Timetable
from .weighting import (
    CLASH_PENALTY,
    SLIDER_MAX,
    SLIDER_MIN,
    SLIDER_WEIGHTS,
    TAB_OF_CRITERION,
    UNPLACED_PENALTY,
    Weighting,
    WeightingTab,
    slider_to_weight,
)

__all__ = [
    "CLASH_PENALTY",
    "LINES_PER_LESSON",
    "REQUEST_MAX",
    "REQUEST_MIN",
    "SLIDER_MAX",
    "SLIDER_MIN",
    "SLIDER_WEIGHTS",
    "TAB_OF_CRITERION",
    "UNPLACED_PENALTY",
    "UNSET",
    "Assignment",
    "CriterionScore",
    "DataIssue",
    "DateScheme",
    "Department",
    "EntityKind",
    "Evaluation",
    "HalfDay",
    "Lesson",
    "LessonLine",
    "MinMax",
    "PeriodDef",
    "PeriodKind",
    "Room",
    "SchoolClass",
    "SchoolInfo",
    "Severity",
    "StudentGroup",
    "Subject",
    "Teacher",
    "Term",
    "TimeGrid",
    "TimeRequest",
    "Timetable",
    "UnspecifiedKind",
    "UnspecifiedRequest",
    "UntisProject",
    "Weighting",
    "WeightingTab",
    "build_lesson_id",
    "diagnose_data",
    "double_periods_from_block",
    "hhmm_to_minutes",
    "minutes_to_hhmm",
    "slider_to_weight",
    "split_lesson_id",
]
