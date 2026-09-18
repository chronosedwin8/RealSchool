"""El proyecto Untis: agregado de datos maestros, lecciones y horarios.

Es la unidad que se guarda en `.rsp` y la única entrada de `bridge`. Las
colecciones se indexan por id para que la UI y el puente consulten en O(1).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Protocol

from .common import EntityKind
from .lessons import Lesson
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
from .requests import TimeRequest, UnspecifiedRequest
from .time_grid import TimeGrid
from .timetable import Timetable
from .weighting import Weighting


class HasId(Protocol):
    """Cualquier entidad de datos maestros: todas se identifican por `id`."""

    @property
    def id(self) -> str: ...


def _index[T: HasId](items: tuple[T, ...]) -> dict[str, T]:
    indice: dict[str, T] = {}
    for it in items:
        clave = it.id
        if clave in indice:
            raise ValueError(f"Id duplicado en los datos maestros: {clave!r}")
        indice[clave] = it
    return indice


@dataclass(frozen=True, slots=True)
class SchoolInfo:
    """Datos del colegio (cabecera del export XmlInterface)."""

    name: str = ""
    school_year_begin: str = ""
    school_year_end: str = ""
    header1: str = ""
    header2: str = ""
    footer: str = ""
    term_name: str = ""
    school_type: str = ""
    term_begin: str = ""
    """Fecha `AAAAMMDD` de inicio del período lectivo del export."""
    term_end: str = ""
    """Fecha `AAAAMMDD` de fin del período lectivo del export."""
    first_period: int = 1
    """Número con el que Untis rotula el primer período (0 si el colegio usa
    "hora cero"). El XmlInterface numera siempre desde 1; los archivos GPU001
    usan este rótulo, así que la importación y la exportación GPU lo aplican."""

    def __post_init__(self) -> None:
        if self.first_period not in (0, 1):
            raise ValueError(f"El primer período es 0 o 1: {self.first_period}")


@dataclass(frozen=True, slots=True)
class UntisProject:
    """Proyecto completo: lo que el usuario abre, edita, optimiza y exporta."""

    school: SchoolInfo = field(default_factory=SchoolInfo)
    time_grids: tuple[TimeGrid, ...] = field(default_factory=tuple)
    departments: tuple[Department, ...] = field(default_factory=tuple)
    classes: tuple[SchoolClass, ...] = field(default_factory=tuple)
    teachers: tuple[Teacher, ...] = field(default_factory=tuple)
    rooms: tuple[Room, ...] = field(default_factory=tuple)
    subjects: tuple[Subject, ...] = field(default_factory=tuple)
    student_groups: tuple[StudentGroup, ...] = field(default_factory=tuple)
    terms: tuple[Term, ...] = field(default_factory=tuple)
    lessons: tuple[Lesson, ...] = field(default_factory=tuple)
    time_requests: tuple[TimeRequest, ...] = field(default_factory=tuple)
    unspecified_requests: tuple[UnspecifiedRequest, ...] = field(default_factory=tuple)
    weighting: Weighting = field(default_factory=Weighting)
    timetables: tuple[Timetable, ...] = field(default_factory=tuple)
    date_schemes: tuple[DateScheme, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        vistos: set[str] = set()
        for tt in self.timetables:
            if tt.id in vistos:
                raise ValueError(f"Id de horario duplicado: {tt.id!r}")
            vistos.add(tt.id)

    # --- índices ---------------------------------------------------------- #

    @property
    def grid_by_id(self) -> dict[str, TimeGrid]:
        return _index(self.time_grids)

    @property
    def class_by_id(self) -> dict[str, SchoolClass]:
        return _index(self.classes)

    @property
    def teacher_by_id(self) -> dict[str, Teacher]:
        return _index(self.teachers)

    @property
    def room_by_id(self) -> dict[str, Room]:
        return _index(self.rooms)

    @property
    def subject_by_id(self) -> dict[str, Subject]:
        return _index(self.subjects)

    @property
    def student_group_by_id(self) -> dict[str, StudentGroup]:
        return _index(self.student_groups)

    @property
    def department_by_id(self) -> dict[str, Department]:
        return _index(self.departments)

    @property
    def term_by_id(self) -> dict[str, Term]:
        return _index(self.terms)

    @property
    def date_scheme_by_id(self) -> dict[str, DateScheme]:
        return _index(self.date_schemes)

    @property
    def lesson_by_number(self) -> dict[int, Lesson]:
        indice: dict[int, Lesson] = {}
        for le in self.lessons:
            if le.number in indice:
                raise ValueError(f"Nº de lección duplicado: {le.number}")
            indice[le.number] = le
        return indice

    # --- consultas -------------------------------------------------------- #

    @property
    def active_lessons(self) -> tuple[Lesson, ...]:
        """Lecciones que entran en la optimización (las marcadas "ignorar", no)."""
        return tuple(le for le in self.lessons if not le.ignore)

    def requests_for(self, kind: EntityKind, entity_id: str) -> tuple[TimeRequest, ...]:
        """Deseos de tiempo de una entidad concreta."""
        return tuple(
            r for r in self.time_requests if r.entity_kind is kind and r.entity_id == entity_id
        )

    def unspecified_for(self, kind: EntityKind, entity_id: str) -> tuple[UnspecifiedRequest, ...]:
        """Deseos no especificados de una entidad concreta."""
        return tuple(
            r
            for r in self.unspecified_requests
            if r.entity_kind is kind and r.entity_id == entity_id
        )

    def grid_for_class(self, class_id: str) -> TimeGrid | None:
        """Rejilla por la que se rige una clase."""
        clase = self.class_by_id.get(class_id)
        if clase is None:
            return None
        return self.grid_by_id.get(clase.time_grid)

    def lessons_of_class(self, class_id: str) -> tuple[Lesson, ...]:
        """Lecciones en las que participa una clase."""
        return tuple(le for le in self.lessons if class_id in le.classes)

    def lessons_of_teacher(self, teacher_id: str) -> tuple[Lesson, ...]:
        """Lecciones en las que participa un profesor."""
        return tuple(le for le in self.lessons if teacher_id in le.teachers)

    def timetable_by_id(self, timetable_id: str) -> Timetable | None:
        """Una versión de horario concreta."""
        for tt in self.timetables:
            if tt.id == timetable_id:
                return tt
        return None

    # --- mutación funcional ------------------------------------------------ #

    def with_weighting(self, weighting: Weighting) -> UntisProject:
        """Copia del proyecto con otra ponderación."""
        return replace(self, weighting=weighting)

    def with_timetable(self, timetable: Timetable) -> UntisProject:
        """Copia del proyecto con ese horario añadido o reemplazado por id."""
        otros = tuple(t for t in self.timetables if t.id != timetable.id)
        return replace(self, timetables=(*otros, timetable))
