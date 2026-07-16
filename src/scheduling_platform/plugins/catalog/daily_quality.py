"""Reglas blandas de estructura diaria (huecos, continuidad, balance, jornada).

Todas razonan sobre la ocupación período-a-período de un recurso
(:mod:`occupancy`), así que **requieren el modo con booleanas de inicio**
(``boolean_starts=True``). Cada una emite variables de holgura que el Scoring
Engine minimiza; ningún horario se vuelve infactible por incumplirlas.

- **SC-02 huecos** (``TeacherGapsPlugin``): períodos libres *entre* clases del
  mismo día.
- **SC-04 continuidad** (``TaskContinuityPlugin``): número de bloques separados
  de clase al día (menos fragmentación = menos bloques).
- **SC-05 balance semanal** (``WeeklyBalancePlugin``): minimiza la carga del día
  más cargado, repartiendo las clases entre los días.
- **SC-07 jornada** (``DailySpanPlugin``): longitud de la jornada (del primer al
  último período ocupado); una jornada más corta es preferible.
- **SC-08 consecutivas** (``SoftMaxConsecutivePlugin``): versión penalizada del
  máximo de períodos seguidos (la dura vive en ``load.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ...dsl.domain import BoolDomain, IntDomain
from ...dsl.expressions import LinearExpr, Var
from ...dsl.logic import DslConstraint, LinearConstraint
from ..base import Contribution, PenaltyTerm, SchedulingPlugin
from ..context import SchedulingModelContext
from .occupancy import busy_var, day_slots


def _resources_with(context: SchedulingModelContext, tag: str) -> list[int]:
    return [int(r.id) for r in context.problem.resources if tag in r.tags]


def _sum(variables: list[Var]) -> LinearExpr:
    return LinearExpr.from_terms((v, 1) for v in variables)


@dataclass(frozen=True, slots=True)
class TeacherGapsPlugin(SchedulingPlugin):
    """SC-02: penaliza los períodos libres intercalados entre clases del día."""

    name: ClassVar[str] = "teacher_gaps"
    tag: str = "teacher"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints: list[DslConstraint] = []
        gap_vars: list[Var] = []

        for rid in _resources_with(context, self.tag):
            for start, end in day_slots(context):
                slots = list(range(start, end))
                if len(slots) < 3:
                    continue  # sin al menos 3 períodos no puede haber hueco interno
                busy: dict[int, Var] = {}
                for slot in slots:
                    var, links = busy_var(context, rid, slot)
                    busy[slot] = var
                    constraints.extend(links)

                # before[p] = hay clase en algún período anterior del día (monótona)
                before: dict[int, Var] = {}
                for i, slot in enumerate(slots):
                    b = Var(f"before#r{rid}#k{slot}", BoolDomain())
                    before[slot] = b
                    if i > 0:
                        prev_slot = slots[i - 1]
                        constraints.append(LinearConstraint((b - before[prev_slot]) >= 0))
                        constraints.append(LinearConstraint((b - busy[prev_slot]) >= 0))

                # after[p] = hay clase en algún período posterior del día (monótona)
                after: dict[int, Var] = {}
                for i in range(len(slots) - 1, -1, -1):
                    slot = slots[i]
                    a = Var(f"after#r{rid}#k{slot}", BoolDomain())
                    after[slot] = a
                    if i < len(slots) - 1:
                        next_slot = slots[i + 1]
                        constraints.append(LinearConstraint((a - after[next_slot]) >= 0))
                        constraints.append(LinearConstraint((a - busy[next_slot]) >= 0))

                # hueco: libre (busy=0) con clase antes y después
                for slot in slots[1:-1]:
                    gap = Var(f"gap#r{rid}#k{slot}", BoolDomain())
                    gap_vars.append(gap)
                    constraints.append(
                        LinearConstraint((gap - before[slot] - after[slot] + busy[slot]) >= -1)
                    )

        if not gap_vars:
            return Contribution(constraints=tuple(constraints))
        return Contribution(
            constraints=tuple(constraints),
            penalties=(PenaltyTerm(_sum(gap_vars), self.weight, "teacher_gaps"),),
        )


@dataclass(frozen=True, slots=True)
class TaskContinuityPlugin(SchedulingPlugin):
    """SC-04: penaliza cada bloque de clase separado (fomenta la continuidad)."""

    name: ClassVar[str] = "task_continuity"
    tag: str = "group"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints: list[DslConstraint] = []
        blk_vars: list[Var] = []

        for rid in _resources_with(context, self.tag):
            for start, end in day_slots(context):
                slots = list(range(start, end))
                if len(slots) < 2:
                    continue
                busy: dict[int, Var] = {}
                for slot in slots:
                    var, links = busy_var(context, rid, slot)
                    busy[slot] = var
                    constraints.extend(links)

                for i, slot in enumerate(slots):
                    blk = Var(f"blk#r{rid}#k{slot}", BoolDomain())
                    blk_vars.append(blk)
                    if i == 0:
                        # un bloque arranca si el primer período está ocupado
                        constraints.append(LinearConstraint((blk - busy[slot]) >= 0))
                    else:
                        prev_slot = slots[i - 1]
                        constraints.append(
                            LinearConstraint((blk - busy[slot] + busy[prev_slot]) >= 0)
                        )

        if not blk_vars:
            return Contribution(constraints=tuple(constraints))
        return Contribution(
            constraints=tuple(constraints),
            penalties=(PenaltyTerm(_sum(blk_vars), self.weight, "task_continuity"),),
        )


@dataclass(frozen=True, slots=True)
class WeeklyBalancePlugin(SchedulingPlugin):
    """SC-05: minimiza la carga del día más cargado (reparte entre los días)."""

    name: ClassVar[str] = "weekly_balance"
    tag: str = "group"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints: list[DslConstraint] = []
        peak_vars: list[Var] = []
        days = day_slots(context)
        max_day = max((end - start for start, end in days), default=0)
        if max_day == 0 or len(days) < 2:
            return Contribution()

        for rid in _resources_with(context, self.tag):
            peak = Var(f"bal#r{rid}", IntDomain(0, max_day))
            has_load = False
            for start, end in days:
                busy_vars: list[Var] = []
                for slot in range(start, end):
                    var, links = busy_var(context, rid, slot)
                    constraints.extend(links)
                    busy_vars.append(var)
                if busy_vars:
                    has_load = True
                    # peak >= carga del día
                    constraints.append(LinearConstraint((peak - _sum(busy_vars)) >= 0))
            if has_load:
                peak_vars.append(peak)

        if not peak_vars:
            return Contribution(constraints=tuple(constraints))
        return Contribution(
            constraints=tuple(constraints),
            penalties=(PenaltyTerm(_sum(peak_vars), self.weight, "weekly_balance"),),
        )


@dataclass(frozen=True, slots=True)
class DailySpanPlugin(SchedulingPlugin):
    """SC-07: penaliza la longitud de la jornada (primer a último período)."""

    name: ClassVar[str] = "daily_span"
    tag: str = "teacher"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints: list[DslConstraint] = []
        span_vars: list[Var] = []

        for rid in _resources_with(context, self.tag):
            for start, end in day_slots(context):
                slots = list(range(start, end))
                if len(slots) < 2:
                    continue
                busy: dict[int, Var] = {}
                for slot in slots:
                    var, links = busy_var(context, rid, slot)
                    busy[slot] = var
                    constraints.extend(links)

                # incl_before[p] = clase en algún q <= p ; incl_after[p] = clase en q >= p
                incl_before: dict[int, Var] = {}
                for i, slot in enumerate(slots):
                    ib = Var(f"spanb#r{rid}#k{slot}", BoolDomain())
                    incl_before[slot] = ib
                    constraints.append(LinearConstraint((ib - busy[slot]) >= 0))
                    if i > 0:
                        constraints.append(LinearConstraint((ib - incl_before[slots[i - 1]]) >= 0))

                incl_after: dict[int, Var] = {}
                for i in range(len(slots) - 1, -1, -1):
                    slot = slots[i]
                    ia = Var(f"spana#r{rid}#k{slot}", BoolDomain())
                    incl_after[slot] = ia
                    constraints.append(LinearConstraint((ia - busy[slot]) >= 0))
                    if i < len(slots) - 1:
                        constraints.append(LinearConstraint((ia - incl_after[slots[i + 1]]) >= 0))

                for slot in slots:
                    present = Var(f"span#r{rid}#k{slot}", BoolDomain())
                    span_vars.append(present)
                    constraints.append(
                        LinearConstraint((present - incl_before[slot] - incl_after[slot]) >= -1)
                    )

        if not span_vars:
            return Contribution(constraints=tuple(constraints))
        return Contribution(
            constraints=tuple(constraints),
            penalties=(PenaltyTerm(_sum(span_vars), self.weight, "daily_span"),),
        )


@dataclass(frozen=True, slots=True)
class SoftMaxConsecutivePlugin(SchedulingPlugin):
    """SC-08: penaliza superar ``max_run`` períodos de clase seguidos.

    ``limits`` asocia un tag de categoría con su máximo blando, p. ej.
    ``(("teacher", 3),)``. Por cada ventana de ``max_run + 1`` períodos contiguos
    del día se añade una holgura ``exceso >= ocupación - max_run`` que se penaliza.
    """

    name: ClassVar[str] = "soft_max_consecutive"
    limits: tuple[tuple[str, int], ...] = ()
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        constraints: list[DslConstraint] = []
        slack_vars: list[Var] = []

        for tag, max_run in self.limits:
            if max_run < 1:
                continue
            window = max_run + 1
            for rid in _resources_with(context, tag):
                for start, end in day_slots(context):
                    for first in range(start, end - window + 1):
                        busy_vars: list[Var] = []
                        for slot in range(first, first + window):
                            var, links = busy_var(context, rid, slot)
                            constraints.extend(links)
                            busy_vars.append(var)
                        slack = Var(f"slack#consec#r{rid}#w{first}", IntDomain(0, window))
                        slack_vars.append(slack)
                        # sum(busy) - slack <= max_run
                        expr = _sum(busy_vars) - slack
                        constraints.append(LinearConstraint(expr <= max_run))

        if not slack_vars:
            return Contribution(constraints=tuple(constraints))
        return Contribution(
            constraints=tuple(constraints),
            penalties=(PenaltyTerm(_sum(slack_vars), self.weight, "soft_max_consecutive"),),
        )
