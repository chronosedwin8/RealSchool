"""Reglas blandas de calidad del horario.

A diferencia de las preferencias horarias (Fase 8), estas puntúan propiedades
*globales* del horario que un colegio valora de verdad. La primera:

**Estabilidad de aula (``TeacherRoomStabilityPlugin``).** Cada aula distinta que
un docente usa a lo largo de la semana es un desplazamiento más (material que
cargar, tiempo entre clases). El objetivo penaliza el número de aulas distintas
por docente, empujando a concentrar a cada profesor en las menos posibles.

Se expresa sobre las variables ``assign`` ya existentes (modo compacto, sin
booleanas de período): por cada par (docente, aula) se crea un indicador
``uses`` que se activa si alguna clase del docente usa esa aula, y se penaliza su
suma. Solo se consideran las clases de **un único docente**: en una clase
compartida las N aulas se reparten entre los N profesores de forma simétrica, y
atribuir un aula a un profesor concreto no está determinado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ...core.task import Task
from ...dsl.domain import BoolDomain
from ...dsl.expressions import LinearExpr, Var
from ...dsl.logic import DslConstraint, LinearConstraint
from ..base import Contribution, PenaltyTerm, SchedulingPlugin
from ..context import SchedulingModelContext

_TEACHER_PREFIX = "teacher#"
_ROOMPOOL_PREFIX = "roompool#"


@dataclass(frozen=True, slots=True)
class TeacherRoomStabilityPlugin(SchedulingPlugin):
    """Penaliza cada aula distinta que usa un docente (menos desplazamientos)."""

    name: ClassVar[str] = "teacher_room_stability"
    weight: int = 1

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        problem = context.problem
        constraints: list[DslConstraint] = []
        uses_vars: list[Var] = []

        for resource in problem.resources:
            teacher_tag = next((t for t in resource.tags if t.startswith(_TEACHER_PREFIX)), None)
            if teacher_tag is None:
                continue
            trid = int(resource.id)
            tasks = [t for t in context.tasks_for_resource(trid) if _single_teacher(t)]
            if not tasks:
                continue

            # (aula -> tareas del docente que podrían usarla)
            room_tasks: dict[int, list[int]] = {}
            for task in tasks:
                tid = int(task.id)
                for req in task.requirements:
                    if not req.tag.startswith(_ROOMPOOL_PREFIX):
                        continue
                    for rid in context.eligible_resources(tid, req.tag):
                        room_tasks.setdefault(rid, []).append(tid)

            for rid, tids in room_tasks.items():
                uses = Var(f"uses#tea{trid}#room{rid}", BoolDomain())
                uses_vars.append(uses)
                for tid in tids:
                    # assign[tarea, aula] -> uses[docente, aula]
                    constraints.append(LinearConstraint((context.assign_var(tid, rid) - uses) <= 0))

        if not uses_vars:
            return Contribution(constraints=tuple(constraints))
        expr = LinearExpr.from_terms((v, 1) for v in uses_vars)
        return Contribution(
            constraints=tuple(constraints),
            penalties=(PenaltyTerm(expr, self.weight, "teacher_room_stability"),),
        )


def _single_teacher(task: Task) -> bool:
    return sum(1 for r in task.requirements if r.tag.startswith(_TEACHER_PREFIX)) == 1
