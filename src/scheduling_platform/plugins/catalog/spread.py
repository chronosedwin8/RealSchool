"""Distribución de materias (Fase 7): evitar repetir la misma materia el mismo día.

Penaliza cada sesión de una materia por encima de **una al día** en un grupo, de
modo que, p. ej., 5 horas de Matemáticas se repartan 1 por día. Es blanda (nunca
vuelve infactible el horario) y cuenta **sesiones** (inicios), así que un bloque
doble cuenta como una sola sesión. Requiere las booleanas de inicio.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import ClassVar

from ...core.task import Task
from ...dsl.domain import IntDomain
from ...dsl.expressions import LinearExpr, Var
from ...dsl.logic import DslConstraint, LinearConstraint
from ..base import Contribution, PenaltyTerm, SchedulingPlugin
from ..context import SchedulingModelContext


def _subject_of(task: Task) -> str:
    return task.name.split(" · ", 1)[0]


@dataclass(frozen=True, slots=True)
class SubjectSpreadPlugin(SchedulingPlugin):
    """Penaliza repetir una materia el mismo día en un grupo (reparte por días)."""

    name: ClassVar[str] = "subject_spread"
    weight: int = 8

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        subjects = sorted({_subject_of(t) for t in context.problem.tasks})
        subject_index = {name: i for i, name in enumerate(subjects)}
        constraints: list[DslConstraint] = []
        slack_vars: list[Var] = []
        for resource in context.problem.resources:
            if "group" not in resource.tags:
                continue
            rid = int(resource.id)
            by_subject: dict[str, list[Task]] = defaultdict(list)
            for task in context.tasks_for_resource(rid):
                if any(req.tag in resource.tags for req in task.requirements):
                    by_subject[_subject_of(task)].append(task)
            for subject, tasks in by_subject.items():
                if len(tasks) < 2:
                    continue  # una sola sesión: nunca se repite
                for segment in context.problem.grid.segments:
                    starts = [
                        context.start_var(int(task.id), slot)
                        for task in tasks
                        for slot in context.valid_starts(int(task.id))
                        if int(segment.start) <= slot < int(segment.end)
                    ]
                    if len(starts) < 2:
                        continue
                    slack = Var(
                        f"spread#r{rid}#j{subject_index[subject]}#d{segment.id}",
                        IntDomain(0, len(starts)),
                    )
                    # slack >= (sum de inicios ese día) - 1
                    terms = [(v, 1) for v in starts]
                    terms.append((slack, -1))
                    constraints.append(LinearConstraint(LinearExpr.from_terms(terms) <= 1))
                    slack_vars.append(slack)
        if not slack_vars:
            return Contribution(constraints=tuple(constraints))
        penalty = PenaltyTerm(
            LinearExpr.from_terms((v, 1) for v in slack_vars), self.weight, "subject_spread"
        )
        return Contribution(constraints=tuple(constraints), penalties=(penalty,))
