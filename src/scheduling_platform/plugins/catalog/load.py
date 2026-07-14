"""Reglas duras de carga: máximo diario y máximo de períodos consecutivos.

Aplican a cualquier categoría de recurso identificada por un tag (``teacher``,
``group``...), de modo que una sola instancia del plugin cubre docentes y
grupos a la vez (evitando colisiones de nombre en el registro).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from ...core.resource import Resource
from ...core.task import Task
from ...dsl.expressions import LinearExpr, Var
from ...dsl.logic import DslConstraint, LinearConstraint
from ..base import Contribution, SchedulingPlugin
from ..context import SchedulingModelContext


def _linear_sum(variables: Iterable[Var]) -> LinearExpr:
    acc = LinearExpr.of(0)
    for variable in variables:
        acc = acc + variable
    return acc


def _eligible(task: Task, resource: Resource) -> bool:
    return any(req.tag in resource.tags for req in task.requirements)


@dataclass(frozen=True, slots=True)
class MaxDailyLoadPlugin(SchedulingPlugin):
    """Límite de períodos que un recurso puede ocupar por día (segmento).

    ``limits`` asocia un tag de categoría con su máximo diario, p. ej.
    ``(("teacher", 6), ("group", 8))``.
    """

    name: ClassVar[str] = "max_daily_load"
    limits: tuple[tuple[str, int], ...] = ()

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints: list[DslConstraint] = []
        for resource in context.problem.resources:
            for tag, max_load in self.limits:
                if tag not in resource.tags:
                    continue
                self._limit_resource(context, resource, max_load, constraints)
        return Contribution(constraints=tuple(constraints))

    def _limit_resource(
        self,
        context: SchedulingModelContext,
        resource: Resource,
        max_load: int,
        constraints: list[DslConstraint],
    ) -> None:
        rid = int(resource.id)
        candidates = [t for t in context.problem.tasks if _eligible(t, resource)]
        for segment in context.problem.grid.segments:
            occ_vars: list[Var] = []
            for task in candidates:
                for slot in range(int(segment.start), int(segment.end)):
                    if not context.covering_starts(task, slot):
                        continue
                    occ, links = context.occupancy(task, rid, slot)
                    constraints.extend(links)
                    occ_vars.append(occ)
            if occ_vars:
                constraints.append(LinearConstraint(_linear_sum(occ_vars) <= max_load))


@dataclass(frozen=True, slots=True)
class MaxConsecutivePlugin(SchedulingPlugin):
    """Límite de períodos consecutivos ocupados por un recurso dentro de un día.

    Para cada ventana de ``max + 1`` slots contiguos de un día, la ocupación
    total debe ser ``<= max``: así queda al menos un período libre y nunca hay
    una racha de ``max + 1``.
    """

    name: ClassVar[str] = "max_consecutive"
    limits: tuple[tuple[str, int], ...] = ()

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints: list[DslConstraint] = []
        for resource in context.problem.resources:
            for tag, max_run in self.limits:
                if tag not in resource.tags or max_run < 1:
                    continue
                self._limit_resource(context, resource, max_run, constraints)
        return Contribution(constraints=tuple(constraints))

    def _limit_resource(
        self,
        context: SchedulingModelContext,
        resource: Resource,
        max_run: int,
        constraints: list[DslConstraint],
    ) -> None:
        rid = int(resource.id)
        candidates = [t for t in context.problem.tasks if _eligible(t, resource)]
        window = max_run + 1
        for segment in context.problem.grid.segments:
            start, end = int(segment.start), int(segment.end)
            for first in range(start, end - window + 1):
                occ_vars: list[Var] = []
                for slot in range(first, first + window):
                    for task in candidates:
                        if not context.covering_starts(task, slot):
                            continue
                        occ, links = context.occupancy(task, rid, slot)
                        constraints.extend(links)
                        occ_vars.append(occ)
                if occ_vars:
                    constraints.append(LinearConstraint(_linear_sum(occ_vars) <= max_run))
