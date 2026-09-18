"""Tipos de apoyo compartidos por las entidades de datos maestros.

Vocabulario Untis: los nombres de campo replican los de la cuadrícula de datos
maestros para que el mapeo con GPU y XmlInterface sea 1:1 (ver
`REFACTOR_UNTIS_MAESTRO.md`, sección 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

#: Valor mínimo de un deseo de tiempo (Zeitwunsch): "imposible", duro por defecto.
REQUEST_MIN: Final = -3
#: Valor máximo de un deseo de tiempo: "muy deseable", duro por defecto.
REQUEST_MAX: Final = 3


class EntityKind(StrEnum):
    """Entidad a la que pertenece un deseo de tiempo o una asignación."""

    CLASS = "class"
    TEACHER = "teacher"
    ROOM = "room"
    SUBJECT = "subject"
    STUDENT_GROUP = "student_group"


class PeriodKind(StrEnum):
    """Tipo de período dentro de la rejilla de tiempo."""

    LESSON = "lesson"
    BREAK = "break"


class HalfDay(StrEnum):
    """Media jornada; Untis cuenta huecos y "un solo período" por media jornada."""

    MORNING = "morning"
    AFTERNOON = "afternoon"


@dataclass(frozen=True, slots=True)
class MinMax:
    """Rango inclusivo opcional (`None` = sin límite por ese extremo).

    Replica las columnas mín./máx. de la cuadrícula de Untis (períodos por día,
    huecos, almuerzo, ...). Un rango sin ambos extremos es `MinMax.UNSET`.
    """

    min: int | None = None
    max: int | None = None

    def __post_init__(self) -> None:
        if self.min is not None and self.min < 0:
            raise ValueError(f"MinMax.min no puede ser negativo: {self.min}")
        if self.max is not None and self.max < 0:
            raise ValueError(f"MinMax.max no puede ser negativo: {self.max}")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"MinMax inconsistente: min={self.min} > max={self.max}")

    @property
    def is_set(self) -> bool:
        """`True` si al menos un extremo está definido."""
        return self.min is not None or self.max is not None

    def contains(self, value: int) -> bool:
        """`True` si `value` respeta ambos extremos definidos."""
        if self.min is not None and value < self.min:
            return False
        return not (self.max is not None and value > self.max)


#: Rango sin restricción, usado como valor por defecto en los datos maestros.
UNSET: Final = MinMax()
