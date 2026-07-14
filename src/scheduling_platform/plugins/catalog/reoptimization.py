"""Congelado de partes del horario (base de la reoptimización).

Fijar una clase ya ubicada es, sencillamente, otra regla dura: se expresa como
plugin y entra por el mismo pipeline. El núcleo no necesita saber nada de
"reoptimizar".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ...dsl.logic import DslConstraint, LinearConstraint
from ..base import Contribution, SchedulingPlugin
from ..context import SchedulingModelContext


@dataclass(frozen=True, slots=True)
class FrozenClass:
    """Una clase cuya ubicación y recursos quedan fijados."""

    task_id: int
    start: int
    resource_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class FrozenSchedulePlugin(SchedulingPlugin):
    """Fija las clases congeladas: mismo período y mismos recursos que la base."""

    name: ClassVar[str] = "frozen_schedule"
    frozen: tuple[FrozenClass, ...] = field(default_factory=tuple)

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints: list[DslConstraint] = []
        for clase in self.frozen:
            if clase.start not in context.valid_starts(clase.task_id):
                continue  # la base ya no es válida para este problema
            constraints.append(
                LinearConstraint(context.start_var(clase.task_id, clase.start).eq(1))
            )
            for rid in clase.resource_ids:
                constraints.append(LinearConstraint(context.assign_var(clase.task_id, rid).eq(1)))
        return Contribution(constraints=tuple(constraints))
