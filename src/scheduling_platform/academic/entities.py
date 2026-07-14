"""Entidades del dominio académico (Fase 2).

Conjunto representativo y suficiente para traducir a un problema canónico y
generar un horario. Las entidades organizativas (Sede, Edificio, Nivel,
Sección, Estudiante) y las temporales de detalle (Receso, Almuerzo, Evento,
Calendario) se incorporarán en fases posteriores sin rehacer el adaptador,
porque o bien *agrupan* estas entidades o se expresan como *restricciones*
(Fase 8). Justificación en ADR-006.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.exceptions import require
from .exceptions import InvalidAcademicEntity
from .ids import AssignmentId, GroupId, RoomId, SubjectId, TeacherId


@dataclass(frozen=True, slots=True)
class Room:
    """Aula o laboratorio. ``capacity`` = asientos (no capacidad canónica).

    Los asientos son un dato para la restricción ``size <= asientos`` de la
    Fase 8; en el Modelo Canónico un aula es un recurso unario (una clase a la
    vez). ``room_type`` y ``equipment`` alimentan el emparejamiento por tags.
    """

    id: RoomId
    name: str
    capacity: int = 1
    room_type: str = "standard"
    equipment: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        require(self.id >= 0, InvalidAcademicEntity, f"id de aula negativo: {self.id}")
        require(
            bool(self.name.strip()), InvalidAcademicEntity, "el nombre del aula no puede ser vacío"
        )
        require(
            self.capacity >= 1, InvalidAcademicEntity, f"capacidad de aula < 1: {self.capacity}"
        )
        require(bool(self.room_type.strip()), InvalidAcademicEntity, "room_type no puede ser vacío")


@dataclass(frozen=True, slots=True)
class Teacher:
    """Docente. ``available_periods`` = ``(día, período)`` en los que puede dar clase.

    ``None`` significa disponibilidad total. El adaptador convierte la
    disponibilidad en el dominio temporal (``allowed_starts``) de las tareas
    del docente.
    """

    id: TeacherId
    name: str
    available_periods: frozenset[tuple[int, int]] | None = None

    def __post_init__(self) -> None:
        require(self.id >= 0, InvalidAcademicEntity, f"id de docente negativo: {self.id}")
        require(
            bool(self.name.strip()),
            InvalidAcademicEntity,
            "el nombre del docente no puede ser vacío",
        )


@dataclass(frozen=True, slots=True)
class StudentGroup:
    """Grupo/curso de estudiantes. ``size`` = número de estudiantes."""

    id: GroupId
    name: str
    size: int = 1

    def __post_init__(self) -> None:
        require(self.id >= 0, InvalidAcademicEntity, f"id de grupo negativo: {self.id}")
        require(
            bool(self.name.strip()), InvalidAcademicEntity, "el nombre del grupo no puede ser vacío"
        )
        require(self.size >= 1, InvalidAcademicEntity, f"tamaño de grupo < 1: {self.size}")


@dataclass(frozen=True, slots=True)
class Subject:
    """Materia/asignatura."""

    id: SubjectId
    name: str

    def __post_init__(self) -> None:
        require(self.id >= 0, InvalidAcademicEntity, f"id de materia negativo: {self.id}")
        require(
            bool(self.name.strip()),
            InvalidAcademicEntity,
            "el nombre de la materia no puede ser vacío",
        )


@dataclass(frozen=True, slots=True)
class TeachingAssignment:
    """Carga académica: un docente imparte una materia a un grupo.

    ``session_lengths`` describe las sesiones semanales por su duración en
    períodos: ``(2, 2, 1)`` son tres sesiones (dos bloques dobles y una sencilla,
    5 períodos/semana). Cada entrada generará una tarea canónica.
    ``required_room_type`` restringe el aula a un tipo concreto (p. ej. ``lab``).
    """

    id: AssignmentId
    teacher_id: TeacherId
    subject_id: SubjectId
    group_id: GroupId
    session_lengths: tuple[int, ...]
    required_room_type: str | None = None

    def __post_init__(self) -> None:
        require(self.id >= 0, InvalidAcademicEntity, f"id de carga negativo: {self.id}")
        require(
            len(self.session_lengths) >= 1,
            InvalidAcademicEntity,
            "la carga necesita >= 1 sesión",
        )
        require(
            all(length >= 1 for length in self.session_lengths),
            InvalidAcademicEntity,
            f"duración de sesión < 1 en {self.session_lengths}",
        )
