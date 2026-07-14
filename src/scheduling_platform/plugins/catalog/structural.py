"""Plugins estructurales fundamentales (correctitud del horario)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from ...core.resource import Resource
from ...core.task import Task
from ...dsl.domain import BoolDomain
from ...dsl.expressions import LinearExpr, Var
from ...dsl.logic import (
    DslConstraint,
    DslLiteral,
    IntervalSpec,
    LinearConstraint,
    NoOverlapConstraint,
)
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
        constraints: list[LinearConstraint] = []
        for resource in context.problem.resources:
            if resource.capacity != 1:
                continue
            candidates = list(context.tasks_for_resource(int(resource.id)))
            if len(candidates) < 2:
                continue
            self._add_no_overlap(context, resource, candidates, constraints)
        return Contribution(constraints=tuple(constraints))

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


class IntervalNoOverlapPlugin(SchedulingPlugin):
    """No-solape en formulación **compacta**, con intervalos opcionales.

    Equivalente a :class:`ResourceNoOverlapPlugin`, pero en vez de una variable
    de ocupación por (tarea, recurso, período), crea **un intervalo por
    (tarea, recurso elegible)**, presente solo si la tarea usa ese recurso, y
    delega el no-solape en la restricción global del solver.

    El tamaño del modelo deja de depender del horizonte: pasa de
    O(tareas x recursos x períodos) a O(tareas x recursos). Es la formulación
    que hace viable la escala objetivo (ADR-015).
    """

    name: ClassVar[str] = "interval_no_overlap"

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        problem = context.problem
        constraints: list[DslConstraint] = []

        # Enlace start (booleanas) <-> tstart (entera). En modo compacto no hay
        # booleanas que enlazar: 'tstart' ya lleva los inicios válidos en su dominio.
        if context.boolean_starts:
            for task in problem.tasks:
                if context.valid_starts(int(task.id)):
                    constraints.append(context.start_channeling(int(task.id)))

        for resource in problem.resources:
            if resource.capacity != 1:
                continue
            rid = int(resource.id)
            intervals = tuple(
                IntervalSpec(
                    start=context.task_start_var(int(task.id)),
                    size=task.duration,
                    presence=DslLiteral(context.assign_var(int(task.id), rid)),
                )
                for task in context.tasks_for_resource(rid)
                if context.valid_starts(int(task.id))
            )
            if len(intervals) >= 2:
                constraints.append(NoOverlapConstraint(intervals))

        return Contribution(constraints=tuple(constraints))


def default_structural_plugins() -> tuple[SchedulingPlugin, ...]:
    """Plugins que conviene activar siempre para producir horarios correctos.

    Se usa la formulación compacta con intervalos: misma semántica que la
    booleana pero con un modelo mucho más pequeño.
    """
    return (IntervalNoOverlapPlugin(),)
