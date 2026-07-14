"""Recurso: entidad que puede ser ocupada por tareas (D3).

Un recurso genérico (en el dominio académico: docente, aula, grupo...) porta
un conjunto de ``tags`` que satisfacen requerimientos de tareas y una
``capacity``. Con ``capacity == 1`` el recurso es unario/disyuntivo (solo una
tarea a la vez); con capacidad mayor admite uso simultáneo hasta ese cupo,
lo que habilitará restricciones ``Cumulative`` en el modelo (Fase 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .exceptions import InvalidEntity, require
from .ids import ResourceId


@dataclass(frozen=True, slots=True)
class Resource:
    """Entidad ocupable identificada por un ``ResourceId`` entero."""

    id: ResourceId
    name: str
    tags: frozenset[str] = field(default_factory=frozenset)
    capacity: int = 1

    def __post_init__(self) -> None:
        require(self.id >= 0, InvalidEntity, f"id de recurso negativo: {self.id}")
        require(bool(self.name.strip()), InvalidEntity, "el nombre del recurso no puede ser vacío")
        require(self.capacity >= 1, InvalidEntity, f"capacity < 1: {self.capacity}")

    @property
    def is_unary(self) -> bool:
        """``True`` si el recurso solo admite una tarea simultánea."""
        return self.capacity == 1

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags
