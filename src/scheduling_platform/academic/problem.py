"""Agregado del dominio académico: el problema escolar completo.

Reúne el marco horario, la infraestructura, el cuerpo docente, los grupos, las
materias y las cargas académicas, y valida su integridad referencial: IDs
únicos por colección y cargas que referencian entidades existentes. La
satisfacibilidad estructural profunda (¿hay algún aula del tipo requerido?,
¿cabe la demanda de horas?) se delega al Constraint Graph Builder de la Fase 5.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.exceptions import require
from .entities import Room, StudentGroup, Subject, Teacher, TeachingAssignment
from .exceptions import AcademicIntegrityError
from .ids import AssignmentId, GroupId, RoomId, SubjectId, TeacherId
from .time_frame import TimeFrame


@dataclass(frozen=True, slots=True)
class AcademicProblem:
    """Descripción completa e inmutable de un problema académico."""

    time_frame: TimeFrame
    rooms: tuple[Room, ...]
    teachers: tuple[Teacher, ...]
    groups: tuple[StudentGroup, ...]
    subjects: tuple[Subject, ...]
    assignments: tuple[TeachingAssignment, ...]

    def __post_init__(self) -> None:
        require(len(self.rooms) >= 1, AcademicIntegrityError, "se necesita >= 1 aula")
        require(len(self.teachers) >= 1, AcademicIntegrityError, "se necesita >= 1 docente")
        require(len(self.groups) >= 1, AcademicIntegrityError, "se necesita >= 1 grupo")
        require(len(self.subjects) >= 1, AcademicIntegrityError, "se necesita >= 1 materia")
        require(len(self.assignments) >= 1, AcademicIntegrityError, "se necesita >= 1 carga")
        self._check_unique_ids()
        self._check_assignment_references()

    def _check_unique_ids(self) -> None:
        for label, ids in (
            ("aula", [r.id for r in self.rooms]),
            ("docente", [t.id for t in self.teachers]),
            ("grupo", [g.id for g in self.groups]),
            ("materia", [s.id for s in self.subjects]),
            ("carga", [a.id for a in self.assignments]),
        ):
            require(
                len(ids) == len(set(ids)),
                AcademicIntegrityError,
                f"IDs de {label} duplicados",
            )

    def _check_assignment_references(self) -> None:
        teacher_ids = {t.id for t in self.teachers}
        subject_ids = {s.id for s in self.subjects}
        group_ids = {g.id for g in self.groups}
        for a in self.assignments:
            require(
                a.teacher_id in teacher_ids,
                AcademicIntegrityError,
                f"la carga {a.id} referencia un docente inexistente: {a.teacher_id}",
            )
            require(
                a.subject_id in subject_ids,
                AcademicIntegrityError,
                f"la carga {a.id} referencia una materia inexistente: {a.subject_id}",
            )
            require(
                a.group_id in group_ids,
                AcademicIntegrityError,
                f"la carga {a.id} referencia un grupo inexistente: {a.group_id}",
            )

    def room_by_id(self, room_id: RoomId) -> Room:
        for room in self.rooms:
            if room.id == room_id:
                return room
        raise AcademicIntegrityError(f"aula inexistente: {room_id}")

    def teacher_by_id(self, teacher_id: TeacherId) -> Teacher:
        for teacher in self.teachers:
            if teacher.id == teacher_id:
                return teacher
        raise AcademicIntegrityError(f"docente inexistente: {teacher_id}")

    def group_by_id(self, group_id: GroupId) -> StudentGroup:
        for group in self.groups:
            if group.id == group_id:
                return group
        raise AcademicIntegrityError(f"grupo inexistente: {group_id}")

    def subject_by_id(self, subject_id: SubjectId) -> Subject:
        for subject in self.subjects:
            if subject.id == subject_id:
                return subject
        raise AcademicIntegrityError(f"materia inexistente: {subject_id}")

    def assignment_by_id(self, assignment_id: AssignmentId) -> TeachingAssignment:
        for assignment in self.assignments:
            if assignment.id == assignment_id:
                return assignment
        raise AcademicIntegrityError(f"carga inexistente: {assignment_id}")
