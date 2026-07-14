"""Requerimiento de recursos de una tarea (value object).

Una tarea declara *qué tipo* de recurso necesita mediante un ``tag`` (p. ej.
``"teacher"`` o ``"room"``) y una cantidad. El emparejamiento con recursos
concretos que porten ese tag lo resuelve el modelo matemático (Fase 7); el
núcleo solo describe la necesidad.
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import InvalidEntity, require


@dataclass(frozen=True, slots=True)
class ResourceRequirement:
    """Necesidad de ``quantity`` recursos que porten el tag ``tag``."""

    tag: str
    quantity: int = 1

    def __post_init__(self) -> None:
        require(
            bool(self.tag.strip()), InvalidEntity, "el tag del requerimiento no puede ser vacío"
        )
        require(self.quantity >= 1, InvalidEntity, f"quantity < 1: {self.quantity}")
