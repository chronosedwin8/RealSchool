"""Reglas duras de aula."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ...core.ids import ResourceId
from ...dsl.logic import DslConstraint, LinearConstraint
from ..base import Contribution, SchedulingPlugin
from ..context import SchedulingModelContext


@dataclass(frozen=True, slots=True)
class RoomCapacityPlugin(SchedulingPlugin):
    """Un grupo no puede asignarse a un aula con menos asientos que estudiantes.

    Compara el atributo ``size`` de la tarea (tamaño del grupo) con el atributo
    ``seats`` del recurso-aula. Si no cabe, se prohíbe la asignación
    (``assign == 0``); el solver elegirá otra aula o el pipeline explicará la
    infactibilidad. Si faltan los atributos, la regla no aplica.
    """

    name: ClassVar[str] = "room_capacity"
    room_tag: str = "room"

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        problem = context.problem
        constraints: list[DslConstraint] = []
        for task in problem.tasks:
            size = task.attribute("size")
            if size <= 0:
                continue
            tid = int(task.id)
            for requirement in task.requirements:
                for rid in context.eligible_resources(tid, requirement.tag):
                    resource = problem.resource_by_id(ResourceId(rid))
                    if self.room_tag not in resource.tags:
                        continue
                    seats = resource.attribute("seats")
                    if seats > 0 and size > seats:
                        constraints.append(LinearConstraint(context.assign_var(tid, rid).eq(0)))
        return Contribution(constraints=tuple(constraints))
