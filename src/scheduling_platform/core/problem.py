"""Agregado raíz de entrada: el problema de calendarización canónico (D5).

Reúne la rejilla temporal, los recursos, las tareas y las restricciones, y
valida su consistencia referencial al construirse: IDs únicos y dominios
temporales coherentes. La satisfacibilidad estructural profunda (p. ej. que
exista algún recurso para cada tag requerido, o que la oferta de tiempo cubra
la demanda) se delega al Constraint Graph Builder de la Fase 5, que además
produce explicaciones legibles.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constraint import Constraint
from .exceptions import ReferentialIntegrityError, require
from .ids import ResourceId, TaskId, TimeSlotIndex
from .resource import Resource
from .task import Task
from .time_grid import TimeGrid


@dataclass(frozen=True, slots=True)
class SchedulingProblem:
    """Descripción completa e inmutable de un problema, lista para el pipeline."""

    grid: TimeGrid
    resources: tuple[Resource, ...]
    tasks: tuple[Task, ...]
    constraints: tuple[Constraint, ...] = ()

    def __post_init__(self) -> None:
        require(
            len(self.resources) >= 1, ReferentialIntegrityError, "el problema necesita >= 1 recurso"
        )
        require(len(self.tasks) >= 1, ReferentialIntegrityError, "el problema necesita >= 1 tarea")
        self._check_unique_ids()
        self._check_task_domains()

    def _check_unique_ids(self) -> None:
        for label, ids in (
            ("recurso", [r.id for r in self.resources]),
            ("tarea", [t.id for t in self.tasks]),
            ("restricción", [c.id for c in self.constraints]),
        ):
            require(
                len(ids) == len(set(ids)),
                ReferentialIntegrityError,
                f"IDs de {label} duplicados",
            )

    def _check_task_domains(self) -> None:
        for task in self.tasks:
            valid = self.grid.valid_starts(task.duration, task.same_segment)
            require(
                len(valid) >= 1,
                ReferentialIntegrityError,
                f"la tarea {task.id} (duración {task.duration}) no cabe en la rejilla",
            )
            if task.allowed_starts is not None:
                fuera = task.allowed_starts - valid
                require(
                    not fuera,
                    ReferentialIntegrityError,
                    f"la tarea {task.id} permite inicios fuera de la rejilla: {sorted(fuera)}",
                )

    @property
    def horizon(self) -> int:
        return self.grid.horizon

    def resource_by_id(self, resource_id: ResourceId) -> Resource:
        for resource in self.resources:
            if resource.id == resource_id:
                return resource
        raise ReferentialIntegrityError(f"recurso inexistente: {resource_id}")

    def task_by_id(self, task_id: TaskId) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise ReferentialIntegrityError(f"tarea inexistente: {task_id}")

    def valid_starts_for(self, task: Task) -> frozenset[TimeSlotIndex]:
        """Inicios válidos efectivos de una tarea (dominio permitido ∩ rejilla)."""
        grid_starts = self.grid.valid_starts(task.duration, task.same_segment)
        if task.allowed_starts is None:
            return grid_starts
        return grid_starts & task.allowed_starts
