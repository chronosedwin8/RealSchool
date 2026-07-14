"""Reglas blandas (preferencias) traducidas a penalizaciones.

No imponen nada al solver: aportan expresiones de holgura ponderadas que se
minimizan en la función objetivo unificada (Scoring Engine). Un horario que las
incumple sigue siendo válido, solo puntúa peor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ...core.ids import TimeSlotIndex
from ...dsl.expressions import LinearExpr
from ..base import Contribution, PenaltyTerm, SchedulingPlugin
from ..context import SchedulingModelContext


@dataclass(frozen=True, slots=True)
class PreferEarlySlotsPlugin(SchedulingPlugin):
    """Prefiere las primeras horas del día (penaliza los inicios tardíos).

    La holgura de cada clase es el índice del período en que empieza dentro de
    su día: cuanto más tarde, más penalización.
    """

    name: ClassVar[str] = "prefer_early_slots"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        grid = context.problem.grid
        expr = LinearExpr.of(0)
        for task in context.problem.tasks:
            tid = int(task.id)
            for slot in context.valid_starts(tid):
                # posición del slot dentro de su día (no el índice global)
                segment = grid.segment_of(TimeSlotIndex(slot))
                offset = slot - int(segment.start)
                if offset:
                    expr = expr + offset * context.start_var(tid, slot)
        if not expr.coeffs:
            return Contribution()
        return Contribution(penalties=(PenaltyTerm(expr, self.weight, "prefer_early_slots"),))


@dataclass(frozen=True, slots=True)
class AvoidSlotsPlugin(SchedulingPlugin):
    """Evita (blandamente) que las clases ocupen ciertos períodos.

    Útil para "evitar últimas horas" o franjas poco deseables. Cada clase que
    ocupe uno de esos períodos suma una unidad de penalización.
    """

    name: ClassVar[str] = "avoid_slots"
    slots: frozenset[int] = field(default_factory=frozenset)
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        if not self.slots:
            return Contribution()
        expr = LinearExpr.of(0)
        for task in context.problem.tasks:
            tid = int(task.id)
            for start in context.valid_starts(tid):
                covered = context.slots_covered(start, task.duration)
                penalizados = sum(1 for slot in covered if slot in self.slots)
                if penalizados:
                    expr = expr + penalizados * context.start_var(tid, start)
        if not expr.coeffs:
            return Contribution()
        return Contribution(penalties=(PenaltyTerm(expr, self.weight, "avoid_slots"),))
