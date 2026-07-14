"""Plugins genéricos de uso común."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ...dsl.logic import LinearConstraint
from ..base import Contribution, SchedulingPlugin
from ..context import SchedulingModelContext


@dataclass(frozen=True, slots=True)
class ForbiddenStartsPlugin(SchedulingPlugin):
    """Prohíbe que ciertas tareas inicien en ciertos slots.

    ``forbidden`` es un conjunto de pares ``(task_id, slot)``; útil para
    bloqueos administrativos y eventos. Demuestra un plugin cuya activación
    cambia el modelo de forma verificable.
    """

    name: ClassVar[str] = "forbidden_starts"
    forbidden: frozenset[tuple[int, int]] = field(default_factory=frozenset)

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints = []
        for task_id, slot in sorted(self.forbidden):
            if slot in context.valid_starts(task_id):
                constraints.append(LinearConstraint(context.start_var(task_id, slot).eq(0)))
        return Contribution(constraints=tuple(constraints))
