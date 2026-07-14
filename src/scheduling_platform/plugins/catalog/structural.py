"""Plugins estructurales fundamentales (correctitud del horario)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from ...core.resource import Resource
from ...core.task import Task
from ...dsl.domain import BoolDomain
from ...dsl.expressions import LinearExpr, Var
from ...dsl.logic import LinearConstraint
from ..base import Contribution, SchedulingPlugin
from ..context import SchedulingModelContext


def _linear_sum(variables: Iterable[Var]) -> LinearExpr:
    acc = LinearExpr.of(0)
    for variable in variables:
        acc = acc + variable
    return acc


class ResourceNoOverlapPlugin(SchedulingPlugin):
    """Ningún recurso unario aloja dos tareas a la vez (no-solape).

    Para cada recurso de capacidad 1 y cada slot, la ocupación total es <= 1.
    La ocupación de una tarea en un recurso y un slot es el AND (linealizado) de
    "la tarea usa el recurso" (``assign``) y "la tarea ocupa el slot" (suma de
    ``start`` que lo cubren). Es una regla estructural de correctitud, por lo que
    conviene tenerla siempre activa (ver ``default_structural_plugins``).
    """

    name: ClassVar[str] = "resource_no_overlap"

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        problem = context.problem
        constraints: list[LinearConstraint] = []
        for resource in problem.resources:
            if resource.capacity != 1:
                continue
            candidates = [t for t in problem.tasks if self._eligible(t, resource)]
            if len(candidates) < 2:
                continue
            self._add_no_overlap(context, resource, candidates, constraints)
        return Contribution(constraints=tuple(constraints))

    @staticmethod
    def _eligible(task: Task, resource: Resource) -> bool:
        return any(req.tag in resource.tags for req in task.requirements)

    def _add_no_overlap(
        self,
        context: SchedulingModelContext,
        resource: Resource,
        candidates: list[Task],
        constraints: list[LinearConstraint],
    ) -> None:
        rid = int(resource.id)
        for slot in range(context.problem.horizon):
            occupants = [
                (task, covering)
                for task in candidates
                if (covering := self._covering_starts(context, task, slot))
            ]
            if len(occupants) < 2:
                continue  # sin posibilidad de choque en este slot
            occ_vars: list[Var] = []
            for task, covering in occupants:
                tid = int(task.id)
                cover_expr = _linear_sum(context.start_var(tid, s) for s in covering)
                assign_var = context.assign_var(tid, rid)
                occ_var = Var(f"occ#t{tid}#r{rid}#k{slot}", BoolDomain())
                # occ = assign AND cover  (linealización del producto de dos 0/1)
                constraints.append(LinearConstraint((occ_var - assign_var) <= 0))
                constraints.append(LinearConstraint((occ_var - cover_expr) <= 0))
                constraints.append(LinearConstraint((occ_var - assign_var - cover_expr) >= -1))
                occ_vars.append(occ_var)
            constraints.append(LinearConstraint(_linear_sum(occ_vars) <= 1))

    @staticmethod
    def _covering_starts(context: SchedulingModelContext, task: Task, slot: int) -> tuple[int, ...]:
        tid = int(task.id)
        return tuple(s for s in context.valid_starts(tid) if s <= slot < s + task.duration)


def default_structural_plugins() -> tuple[SchedulingPlugin, ...]:
    """Plugins que conviene activar siempre para producir horarios correctos."""
    return (ResourceNoOverlapPlugin(),)
