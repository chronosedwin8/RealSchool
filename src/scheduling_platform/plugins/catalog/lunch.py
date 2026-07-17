"""Ventana de almuerzo (Fase 7 E2): al menos una hora libre en un rango.

A diferencia de un almuerzo fijo, define un **rango de períodos** (p. ej. P4-P7)
en los días indicados donde cada docente debe tener **al menos un período libre**
para almorzar; el motor elige cuál. Se modela como el máximo de consecutivas: en
la ventana de ``w`` períodos la ocupación total es ``<= w - 1``, dejando >= 1 libre.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import ClassVar

from ...dsl.expressions import LinearExpr, Var
from ...dsl.logic import DslConstraint, LinearConstraint
from ..base import Contribution, SchedulingPlugin
from ..context import SchedulingModelContext


def _linear_sum(variables: Iterable[Var]) -> LinearExpr:
    acc = LinearExpr.of(0)
    for variable in variables:
        acc = acc + variable
    return acc


@dataclass(frozen=True, slots=True)
class LunchWindowPlugin(SchedulingPlugin):
    """Garantiza >= 1 período libre en la ventana ``[start, end]`` de cada día.

    Aplica a los recursos con el tag ``tag`` (por defecto ``teacher``). ``days``
    limita a ciertos días (índices de segmento); vacío = todos.
    """

    name: ClassVar[str] = "lunch_window"
    start: int = 0
    end: int = 0
    tag: str = "teacher"
    days: tuple[int, ...] = field(default_factory=tuple)

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints: list[DslConstraint] = []
        segments = context.problem.grid.segments
        apply_days = set(self.days) if self.days else set(range(len(segments)))
        for resource in context.problem.resources:
            if self.tag not in resource.tags:
                continue
            rid = int(resource.id)
            candidates = list(context.tasks_for_resource(rid))
            for day, segment in enumerate(segments):
                if day not in apply_days:
                    continue
                lo = int(segment.start) + self.start
                hi = min(int(segment.start) + self.end, int(segment.end) - 1)
                if hi < lo:
                    continue
                window = hi - lo + 1
                occ_vars: list[Var] = []
                for slot in range(lo, hi + 1):
                    for task in candidates:
                        if not context.covering_starts(task, slot):
                            continue
                        occ, links = context.occupancy(task, rid, slot)
                        constraints.extend(links)
                        occ_vars.append(occ)
                if occ_vars:
                    # Ocupación <= tamaño - 1  =>  al menos una hora libre.
                    constraints.append(LinearConstraint(_linear_sum(occ_vars) <= window - 1))
        return Contribution(constraints=tuple(constraints))
