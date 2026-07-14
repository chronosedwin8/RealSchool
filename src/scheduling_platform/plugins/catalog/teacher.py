"""Plugins de reglas de docente."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ...core.task import Task
from ...dsl.logic import LinearConstraint
from ..base import Contribution, SchedulingPlugin
from ..context import SchedulingModelContext


@dataclass(frozen=True, slots=True)
class TeacherLunchPlugin(SchedulingPlugin):
    """Garantiza el almuerzo docente dejando libres ciertos períodos.

    Ninguna clase que requiera un docente puede ocupar un período de almuerzo,
    de modo que todo docente queda libre en la franja. Se expresa prohibiendo
    los inicios cuya duración cubriría un período de ``lunch_slots``. La versión
    granular por docente (con variables de ocupación) llegará en la Fase 8.
    """

    name: ClassVar[str] = "teacher_lunch"
    lunch_slots: frozenset[int] = field(default_factory=frozenset)
    teacher_prefix: str = "teacher"

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints = []
        for task in context.problem.tasks:
            if not self._needs_teacher(task):
                continue
            tid = int(task.id)
            for start in context.valid_starts(tid):
                covered = context.slots_covered(start, task.duration)
                if any(slot in self.lunch_slots for slot in covered):
                    constraints.append(LinearConstraint(context.start_var(tid, start).eq(0)))
        return Contribution(constraints=tuple(constraints))

    def _needs_teacher(self, task: Task) -> bool:
        return any(
            req.tag == self.teacher_prefix or req.tag.startswith(f"{self.teacher_prefix}#")
            for req in task.requirements
        )
