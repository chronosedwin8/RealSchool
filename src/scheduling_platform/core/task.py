"""Tarea: unidad a calendarizar (D3).

Una tarea (en el dominio académico: una sesión de clase) tiene una duración en
slots, un conjunto de requerimientos de recursos y, opcionalmente, un dominio
temporal permitido (``allowed_starts``). ``same_segment`` indica si la tarea
debe caber íntegra dentro de un único segmento de la rejilla (p. ej. un bloque
doble que no debe cruzar el límite del día).
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import InvalidEntity, require
from .ids import TaskId, TimeSlotIndex
from .requirement import ResourceRequirement


@dataclass(frozen=True, slots=True)
class Task:
    """Actividad de ``duration`` slots que consume recursos y ocupa el tiempo."""

    id: TaskId
    name: str
    duration: int
    requirements: tuple[ResourceRequirement, ...]
    allowed_starts: frozenset[TimeSlotIndex] | None = None
    same_segment: bool = True
    attributes: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        require(self.id >= 0, InvalidEntity, f"id de tarea negativo: {self.id}")
        require(bool(self.name.strip()), InvalidEntity, "el nombre de la tarea no puede ser vacío")
        require(self.duration >= 1, InvalidEntity, f"duración < 1: {self.duration}")
        require(len(self.requirements) >= 1, InvalidEntity, "la tarea necesita >= 1 requerimiento")

    def attribute(self, name: str, default: int = 0) -> int:
        """Atributo numérico genérico (p. ej. ``size`` del grupo de la clase)."""
        for key, value in self.attributes:
            if key == name:
                return value
        return default
