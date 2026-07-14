"""Adaptador Dominio Académico -> Modelo Canónico (y reconstrucción inversa).

Traduce un :class:`AcademicProblem` en un
:class:`~scheduling_platform.core.problem.SchedulingProblem` y conserva los
mapeos necesarios para reconstruir un horario académico a partir de una
:class:`~scheduling_platform.core.solution.Solution` (preludio del Solution
Builder de la Fase 9).

Reglas de traducción:
- Docente, grupo y aula -> ``Resource`` canónico unario (capacidad 1: uno a la
  vez). Los asientos del aula no son capacidad canónica.
- Cada sesión de una carga -> un ``Task`` que requiere: el tag único del
  docente, el tag único del grupo y un tag de aula (compartido, para que el
  solver elija).
- La disponibilidad del docente -> ``allowed_starts`` de sus tareas.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..core.ids import ResourceId, TaskId, TimeSlotIndex
from ..core.problem import SchedulingProblem
from ..core.requirement import ResourceRequirement
from ..core.resource import Resource
from ..core.solution import Solution
from ..core.task import Task
from ..core.time_grid import TimeGrid
from .entities import Room, Teacher
from .ids import AssignmentId, GroupId, RoomId, SubjectId, TeacherId
from .problem import AcademicProblem
from .tags import (
    GENERIC_GROUP,
    GENERIC_ROOM,
    GENERIC_TEACHER,
    equipment_tag,
    group_tag,
    room_id_tag,
    room_type_tag,
    teacher_tag,
)
from .time_frame import TimeFrame


@dataclass(frozen=True, slots=True)
class ResourceOrigin:
    """Procedencia académica de un recurso canónico."""

    kind: str  # "teacher" | "room" | "group"
    academic_id: int


@dataclass(frozen=True, slots=True)
class SessionOrigin:
    """Procedencia académica de una tarea canónica (una sesión de una carga)."""

    assignment_id: AssignmentId
    session_index: int


@dataclass(frozen=True, slots=True)
class ScheduledClass:
    """Una clase concreta ya ubicada en día/período con aula asignada."""

    assignment_id: AssignmentId
    teacher_id: TeacherId
    subject_id: SubjectId
    group_id: GroupId
    room_id: RoomId
    day: int
    period: int
    duration: int


@dataclass(frozen=True, slots=True)
class AcademicSchedule:
    """Horario académico reconstruido desde una solución canónica."""

    classes: tuple[ScheduledClass, ...]


@dataclass(frozen=True, slots=True)
class AcademicTranslation:
    """Resultado de la traducción: problema canónico + mapeos de vuelta."""

    academic: AcademicProblem
    problem: SchedulingProblem
    resource_origin: Mapping[ResourceId, ResourceOrigin]
    session_origin: Mapping[TaskId, SessionOrigin]

    def to_schedule(self, solution: Solution) -> AcademicSchedule:
        """Reconstruye el horario académico a partir de una solución canónica."""
        time_frame = self.academic.time_frame
        classes: list[ScheduledClass] = []
        for canonical_assignment in solution.assignments:
            session = self.session_origin[canonical_assignment.task_id]
            carga = self.academic.assignment_by_id(session.assignment_id)
            room_id = self._extract_room(canonical_assignment.resource_ids)
            day, period = time_frame.decode(canonical_assignment.start)
            duration = carga.session_lengths[session.session_index]
            classes.append(
                ScheduledClass(
                    assignment_id=carga.id,
                    teacher_id=carga.teacher_id,
                    subject_id=carga.subject_id,
                    group_id=carga.group_id,
                    room_id=room_id,
                    day=day,
                    period=period,
                    duration=duration,
                )
            )
        return AcademicSchedule(classes=tuple(classes))

    def _extract_room(self, resource_ids: tuple[ResourceId, ...]) -> RoomId:
        for resource_id in resource_ids:
            origin = self.resource_origin[resource_id]
            if origin.kind == "room":
                return RoomId(origin.academic_id)
        raise KeyError("la asignación canónica no contiene un recurso de tipo aula")


class AcademicToCanonicalAdapter:
    """Traductor sin estado del dominio académico al Modelo Canónico."""

    def translate(self, academic: AcademicProblem) -> AcademicTranslation:
        grid = academic.time_frame.to_grid()
        resources: list[Resource] = []
        resource_origin: dict[ResourceId, ResourceOrigin] = {}
        teacher_res: dict[TeacherId, ResourceId] = {}
        group_res: dict[GroupId, ResourceId] = {}
        next_rid = 0

        for teacher in academic.teachers:
            rid = ResourceId(next_rid)
            next_rid += 1
            resources.append(
                Resource(
                    id=rid,
                    name=teacher.name,
                    tags=frozenset({GENERIC_TEACHER, teacher_tag(teacher.id)}),
                    capacity=1,
                )
            )
            resource_origin[rid] = ResourceOrigin("teacher", int(teacher.id))
            teacher_res[teacher.id] = rid

        for group in academic.groups:
            rid = ResourceId(next_rid)
            next_rid += 1
            resources.append(
                Resource(
                    id=rid,
                    name=group.name,
                    tags=frozenset({GENERIC_GROUP, group_tag(group.id)}),
                    capacity=1,
                )
            )
            resource_origin[rid] = ResourceOrigin("group", int(group.id))
            group_res[group.id] = rid

        for room in academic.rooms:
            rid = ResourceId(next_rid)
            next_rid += 1
            resources.append(
                Resource(
                    id=rid,
                    name=room.name,
                    tags=self._room_tags(room),
                    capacity=1,  # un aula aloja una clase a la vez
                    # los asientos NO son capacidad canónica: son un atributo que
                    # consume la regla de capacidad de aula (Fase 8)
                    attributes=(("seats", room.capacity),),
                )
            )
            resource_origin[rid] = ResourceOrigin("room", int(room.id))

        tasks: list[Task] = []
        session_origin: dict[TaskId, SessionOrigin] = {}
        next_tid = 0
        for carga in academic.assignments:
            teacher = academic.teacher_by_id(carga.teacher_id)
            subject = academic.subject_by_id(carga.subject_id)
            group = academic.group_by_id(carga.group_id)
            room_req_tag = (
                room_type_tag(carga.required_room_type)
                if carga.required_room_type is not None
                else GENERIC_ROOM
            )
            for session_index, duration in enumerate(carga.session_lengths):
                tid = TaskId(next_tid)
                next_tid += 1
                tasks.append(
                    Task(
                        id=tid,
                        name=f"{subject.name} · {carga.id}#{session_index}",
                        duration=duration,
                        requirements=(
                            ResourceRequirement(teacher_tag(carga.teacher_id)),
                            ResourceRequirement(group_tag(carga.group_id)),
                            ResourceRequirement(room_req_tag),
                        ),
                        allowed_starts=self._teacher_allowed_starts(
                            teacher, duration, grid, academic.time_frame
                        ),
                        same_segment=True,
                        # el tamaño del grupo alimenta la regla de capacidad de aula
                        attributes=(("size", group.size),),
                    )
                )
                session_origin[tid] = SessionOrigin(carga.id, session_index)

        problem = SchedulingProblem(
            grid=grid,
            resources=tuple(resources),
            tasks=tuple(tasks),
        )
        return AcademicTranslation(
            academic=academic,
            problem=problem,
            resource_origin=resource_origin,
            session_origin=session_origin,
        )

    @staticmethod
    def _room_tags(room: Room) -> frozenset[str]:
        tags = {GENERIC_ROOM, room_id_tag(room.id), room_type_tag(room.room_type)}
        tags.update(equipment_tag(item) for item in room.equipment)
        return frozenset(tags)

    @staticmethod
    def _teacher_allowed_starts(
        teacher: Teacher, duration: int, grid: TimeGrid, time_frame: TimeFrame
    ) -> frozenset[TimeSlotIndex] | None:
        """Inicios donde la sesión cabe completa dentro de la disponibilidad del docente."""
        if teacher.available_periods is None:
            return None
        available = {time_frame.slot_of(day, period) for day, period in teacher.available_periods}
        allowed = {
            start
            for start in grid.valid_starts(duration, same_segment=True)
            if all(TimeSlotIndex(start + offset) in available for offset in range(duration))
        }
        return frozenset(allowed)
