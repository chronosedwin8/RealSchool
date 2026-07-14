"""Restricción como *seam* abstracto del núcleo (D4, ADR-005).

En el modelo canónico una :class:`Constraint` porta únicamente su identidad y
clasificación (dura o blanda). Su contenido algebraico NO vive aquí: se
produce mediante el DSL (Fase 3) y se compila en el CIR (Fase 4). Así el
núcleo respeta el pipeline ``DSL -> CIR -> Solver`` y no conoce CP-SAT.

- Las restricciones **duras** deben satisfacerse sin excepción.
- Las restricciones **blandas** se traducen a variables de holgura penalizadas
  por su ``weight`` en la función objetivo (Fase 8).

No se usa ``slots`` en esta jerarquía: es polimórfica y de bajo volumen
(miles, no millones), por lo que se prioriza flexibilidad sobre densidad.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from .exceptions import InvalidEntity, require
from .ids import ConstraintId


class ConstraintKind(Enum):
    """Clasificación de una restricción."""

    HARD = "hard"
    SOFT = "soft"


@dataclass(frozen=True)
class Constraint(ABC):
    """Contrato abstracto de una regla sobre tasks/resources/slots."""

    id: ConstraintId
    name: str

    def __post_init__(self) -> None:
        require(self.id >= 0, InvalidEntity, f"id de restricción negativo: {self.id}")
        require(
            bool(self.name.strip()), InvalidEntity, "el nombre de la restricción no puede ser vacío"
        )

    @property
    @abstractmethod
    def kind(self) -> ConstraintKind:
        """Clasificación (dura/blanda) de la restricción."""


@dataclass(frozen=True)
class HardConstraint(Constraint):
    """Restricción que el solver debe satisfacer obligatoriamente."""

    @property
    def kind(self) -> ConstraintKind:
        return ConstraintKind.HARD


@dataclass(frozen=True)
class SoftConstraint(Constraint):
    """Preferencia penalizada numéricamente por su ``weight`` (> 0)."""

    weight: int

    def __post_init__(self) -> None:
        super().__post_init__()
        require(self.weight > 0, InvalidEntity, f"weight de restricción blanda <= 0: {self.weight}")

    @property
    def kind(self) -> ConstraintKind:
        return ConstraintKind.SOFT
