"""Acoples de lecciones (Fase 7): clases que ocurren **a la misma hora**.

La Kopplung de Untis en su forma general: en una misma hora pueden dictarse
varias clases simultáneas con distintos profesores, en distintos salones y con
la misma materia o materias distintas (p. ej. BIO11 + GES11 + ING11 a la vez).

Cada clase acoplada porta dos atributos enteros: ``coupling`` (id del acople) y
``cseq`` (índice de la sesión dentro de la semana). Todas las clases que
comparten ``(coupling, cseq)`` deben iniciar en el mismo período: se impone con
igualdades sobre la variable entera ``tstart`` (no necesita inicios booleanos).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ...dsl.expressions import LinearExpr
from ...dsl.logic import DslConstraint, LinearConstraint
from ..base import Contribution, SchedulingPlugin
from ..context import SchedulingModelContext


@dataclass(frozen=True, slots=True)
class CoupledLessonsPlugin(SchedulingPlugin):
    """Fuerza el mismo inicio para las clases que comparten ``(coupling, cseq)``."""

    name: ClassVar[str] = "coupled_lessons"

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        groups: dict[tuple[int, int], list[int]] = {}
        for task in context.problem.tasks:
            cid = task.attribute("coupling", -1)
            if cid < 0:
                continue
            seq = task.attribute("cseq", 0)
            groups.setdefault((cid, seq), []).append(int(task.id))

        constraints: list[DslConstraint] = []
        for ids in groups.values():
            if len(ids) < 2:
                continue
            first = ids[0]
            for other in ids[1:]:
                expr = LinearExpr.from_terms(
                    (
                        (context.task_start_var(first), 1),
                        (context.task_start_var(other), -1),
                    )
                )
                constraints.append(LinearConstraint(expr.eq(0)))
        return Contribution(constraints=tuple(constraints))
