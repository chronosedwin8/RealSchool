"""Solution Builder: de las variables del solver al horario canónico.

Lee los valores de las variables de decisión (``start`` y ``assign``) y
reconstruye una :class:`~scheduling_platform.core.solution.Solution` del Modelo
Canónico. Desde ahí, el adaptador académico puede reconstruir el horario legible
(``AcademicTranslation.to_schedule``).
"""

from __future__ import annotations

from collections.abc import Mapping

from ..core.assignment import Assignment
from ..core.ids import ResourceId, TaskId, TimeSlotIndex
from ..core.solution import Penalty, Solution
from ..plugins.base import PenaltyTerm
from ..plugins.context import SchedulingModelContext
from ..sal.interface import ISolver, SolverVar
from .exceptions import SolutionExtractionError
from .inspector import SolutionInspector


class SolutionBuilder:
    """Reconstruye la solución canónica a partir del solver resuelto."""

    def __init__(self, inspector: SolutionInspector | None = None) -> None:
        self._inspector = inspector if inspector is not None else SolutionInspector()

    def build(
        self,
        context: SchedulingModelContext,
        var_map: Mapping[str, SolverVar],
        solver: ISolver,
        penalties: tuple[PenaltyTerm, ...] = (),
    ) -> Solution:
        values = {key: solver.value(handle) for key, handle in var_map.items()}
        assignments = tuple(
            self._assignment_for(context, values, int(task.id)) for task in context.problem.tasks
        )
        report = self._inspector.penalty_report(penalties, values)
        return Solution(
            assignments=assignments,
            objective_value=solver.objective_value(),
            penalties=report,
        )

    def _assignment_for(
        self, context: SchedulingModelContext, values: Mapping[str, int], task_id: int
    ) -> Assignment:
        start = self._chosen_start(context, values, task_id)
        resources = self._chosen_resources(context, values, task_id)
        if not resources:
            raise SolutionExtractionError(
                f"la tarea {task_id} no tiene ningún recurso asignado en la solución"
            )
        return Assignment(TaskId(task_id), TimeSlotIndex(start), resources)

    @staticmethod
    def _chosen_start(
        context: SchedulingModelContext, values: Mapping[str, int], task_id: int
    ) -> int:
        # La entera 'tstart' ya es el período elegido; existe siempre que el
        # modelo use intervalos. Si no está, se reconstruye desde las booleanas.
        tstart = values.get(context.task_start_var(task_id).key)
        if tstart is not None:
            return tstart
        if context.boolean_starts:
            for slot in context.valid_starts(task_id):
                if values.get(context.start_var(task_id, slot).key) == 1:
                    return slot
        raise SolutionExtractionError(
            f"la tarea {task_id} no tiene ningún inicio activo en la solución"
        )

    @staticmethod
    def _chosen_resources(
        context: SchedulingModelContext, values: Mapping[str, int], task_id: int
    ) -> tuple[ResourceId, ...]:
        task = context.problem.task_by_id(TaskId(task_id))
        chosen: list[int] = []
        for requirement in task.requirements:
            for rid in context.eligible_resources(task_id, requirement.tag):
                if values.get(context.assign_var(task_id, rid).key) == 1 and rid not in chosen:
                    chosen.append(rid)
        return tuple(ResourceId(rid) for rid in sorted(chosen))


__all__ = ["Penalty", "SolutionBuilder"]
