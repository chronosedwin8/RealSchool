"""Datos maestros (Stammdaten): clases, profesores, aulas, materias y grupos.

Cada entidad replica las columnas que Untis muestra en su cuadrícula. Los
campos que el export XmlInterface no trae (mín./máx., deseos) quedan en su valor
neutro y se rellenan desde GPU, desde el `.rsp` o desde la propia UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import UNSET, MinMax


@dataclass(frozen=True, slots=True)
class Department:
    """Departamento; Untis permite planificar y filtrar por departamento."""

    id: str
    name: str = ""

    @property
    def display_name(self) -> str:
        return self.name or self.id


@dataclass(frozen=True, slots=True)
class SchoolClass:
    """Clase (Klasse): el grupo que recibe las lecciones."""

    id: str
    name: str = ""
    time_grid: str = ""
    """Id de la `TimeGrid` por la que se rige esta clase."""
    home_room: str | None = None
    """Aula base (Klassenraum)."""
    department: str | None = None
    students: int = 0
    level: int | None = None
    """Nivel/curso; alimenta secuencias y "materias principales"."""
    periods_per_day: MinMax = UNSET
    lunch_break: MinMax = UNSET
    main_subjects_per_day: int | None = None
    main_subjects_consecutive: int | None = None
    text: str = ""
    """Texto libre de la clase (columna "Text" de Untis)."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("La clase necesita un id")
        if self.students < 0:
            raise ValueError(f"Clase {self.id!r} con alumnos negativos: {self.students}")

    @property
    def display_name(self) -> str:
        return self.name or self.id


@dataclass(frozen=True, slots=True)
class Teacher:
    """Profesor (Lehrer)."""

    id: str
    name: str = ""
    surname: str = ""
    forename: str = ""
    email: str = ""
    department: str | None = None
    home_room: str | None = None
    periods_per_day: MinMax = UNSET
    days_per_week_max: int | None = None
    ntp_per_day: MinMax = UNSET
    """Huecos por día (non-teaching periods)."""
    ntp_per_week: MinMax = UNSET
    """Huecos por semana."""
    lunch_break: MinMax = UNSET
    consecutive_max: int | None = None
    """Períodos seguidos máximo."""
    text: str = ""
    """Texto libre del profesor (columna "Text" de Untis)."""
    status: str = ""
    """Estado laboral tal cual lo guarda Untis (p. ej. `"Docente,"`)."""
    payroll_number: str = ""
    """Número de personal (Personalnummer)."""
    gender: str = ""
    """Género tal cual lo exporta Untis (`"M"`, `"F"`, ...)."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("El profesor necesita un id")
        if self.days_per_week_max is not None and self.days_per_week_max < 0:
            raise ValueError(f"Profesor {self.id!r}: días/semana negativo")
        if self.consecutive_max is not None and self.consecutive_max < 1:
            raise ValueError(f"Profesor {self.id!r}: períodos seguidos máx. < 1")

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        completo = f"{self.forename} {self.surname}".strip()
        return completo or self.id


@dataclass(frozen=True, slots=True)
class Room:
    """Aula (Raum). La cadena de aulas alternativas guía la optimización de aulas."""

    id: str
    name: str = ""
    capacity: int | None = None
    alternative_room: str | None = None
    """Siguiente aula de la cadena de alternativas."""
    room_weight: int = 0
    """Peso de aula 0-4 (Untis: cuánto cuesta no respetar el aula preferida)."""
    department: str | None = None
    text: str = ""
    """Texto libre del aula (columna "Text" de Untis)."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("El aula necesita un id")
        if not 0 <= self.room_weight <= 4:
            raise ValueError(f"Aula {self.id!r}: peso fuera de 0-4: {self.room_weight}")
        if self.capacity is not None and self.capacity < 0:
            raise ValueError(f"Aula {self.id!r}: capacidad negativa")
        if self.alternative_room == self.id:
            raise ValueError(f"Aula {self.id!r}: se lista a sí misma como alternativa")

    @property
    def display_name(self) -> str:
        return self.name or self.id


@dataclass(frozen=True, slots=True)
class Subject:
    """Materia (Fach)."""

    id: str
    name: str = ""
    main_subject: bool = False
    """Materia principal (Hauptfach): mañana preferida, máximo N por día."""
    not_same_day: bool = False
    double_period_required: bool = False
    required_room: str | None = None
    subject_group: str | None = None
    fore_color: str = ""
    """Color de texto tal cual lo guarda Untis (entero decimal en GPU, `#RRGGBB`
    en XmlInterface); se conserva la cadena cruda para no perder el formato."""
    back_color: str = ""
    """Color de fondo, con el mismo formato crudo que `fore_color`."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("La materia necesita un id")

    @property
    def display_name(self) -> str:
        return self.name or self.id


@dataclass(frozen=True, slots=True)
class StudentGroup:
    """Grupo de alumnos (Studentengruppe): acoples IB y grupos de opción."""

    id: str
    name: str = ""
    subject: str | None = None
    classes: tuple[str, ...] = field(default_factory=tuple)
    students: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("El grupo de alumnos necesita un id")
        if self.students < 0:
            raise ValueError(f"Grupo {self.id!r}: alumnos negativos")

    @property
    def display_name(self) -> str:
        return self.name or self.id


@dataclass(frozen=True, slots=True)
class Term:
    """Período lectivo (Periode): acota la validez de una lección dentro del año."""

    id: str
    name: str = ""
    begin: str = ""
    """Fecha `AAAAMMDD` (formato Untis)."""
    end: str = ""
    time_grid: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("El período lectivo necesita un id")
        if self.begin and self.end and self.begin > self.end:
            raise ValueError(f"Período {self.id!r}: empieza después de terminar")

    @property
    def display_name(self) -> str:
        return self.name or self.id


@dataclass(frozen=True, slots=True)
class DateScheme:
    """Esquema de fechas de lección (XmlInterface `lesson_date_scheme`).

    `pattern` es la cadena de Untis con un carácter por día del curso (`1` hay
    clase, `F` festivo, ...) y `periodic_weeks` la periodicidad semanal, ambos
    tal cual vienen en el export.
    """

    id: str
    pattern: str = ""
    periodic_weeks: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("El esquema de fechas necesita un id")

    @property
    def display_name(self) -> str:
        return self.id
