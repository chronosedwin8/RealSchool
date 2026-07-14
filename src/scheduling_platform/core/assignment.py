"""Asignación: una tarea colocada en el tiempo con recursos concretos.

Es el átomo de una :class:`~scheduling_platform.core.solution.Solution`. Sus
invariantes propias son mínimas (no conoce la duración de la tarea ni la
rejilla); la validación cruzada (que el tramo quepa, que los recursos existan)
se realiza a nivel de ``Solution.validate_against(problem)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import InvalidAssignment, require
from .ids import ResourceId, TaskId, TimeSlotIndex


@dataclass(frozen=True, slots=True)
class Assignment:
    """La tarea ``task_id`` inicia en ``start`` usando ``resource_ids``."""

    task_id: TaskId
    start: TimeSlotIndex
    resource_ids: tuple[ResourceId, ...]

    def __post_init__(self) -> None:
        require(self.task_id >= 0, InvalidAssignment, f"task_id negativo: {self.task_id}")
        require(self.start >= 0, InvalidAssignment, f"start negativo: {self.start}")
        require(
            len(self.resource_ids) >= 1, InvalidAssignment, "la asignación necesita >= 1 recurso"
        )

    def end(self, duration: int) -> TimeSlotIndex:
        """Slot final exclusivo dada la duración de la tarea."""
        return TimeSlotIndex(self.start + duration)
