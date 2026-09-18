"""Deseos de tiempo (Zeitwünsche) en la escala -3…+3 de Untis.

-3 ("imposible") y +3 ("obligatorio") son duros por defecto; los valores
intermedios se compilan como términos de objetivo con peso
`time_request_weight x |valor|` (ver sección 6 del documento maestro).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .common import REQUEST_MAX, REQUEST_MIN, EntityKind


class UnspecifiedKind(StrEnum):
    """Tipo de deseo "no especificado" (p. ej. "2 tardes libres, cualquiera")."""

    FREE_DAY = "free_day"
    FREE_MORNING = "free_morning"
    FREE_AFTERNOON = "free_afternoon"


@dataclass(frozen=True, slots=True)
class TimeRequest:
    """Deseo de una entidad sobre una celda, un día completo o un período.

    `day=None` aplica el deseo a ese período en todos los días; `period=None`
    lo aplica al día completo. Ambos a `None` no está permitido: sería un deseo
    sobre toda la semana, que Untis expresa cambiando el valor por defecto.
    """

    entity_kind: EntityKind
    entity_id: str
    value: int
    day: int | None = None
    period: int | None = None

    def __post_init__(self) -> None:
        if not REQUEST_MIN <= self.value <= REQUEST_MAX:
            raise ValueError(f"Deseo fuera de la escala {REQUEST_MIN}…{REQUEST_MAX}: {self.value}")
        if self.day is None and self.period is None:
            raise ValueError("Un deseo necesita día, período o ambos")
        if self.day is not None and self.day < 1:
            raise ValueError(f"Día inválido: {self.day}")
        if self.period is not None and self.period < 1:
            raise ValueError(f"Período inválido: {self.period}")

    @property
    def is_hard(self) -> bool:
        """`True` si el deseo es duro (-3 o +3)."""
        return self.value in (REQUEST_MIN, REQUEST_MAX)

    @property
    def is_block(self) -> bool:
        """`True` si el deseo prohíbe la celda."""
        return self.value == REQUEST_MIN

    @property
    def is_mandatory(self) -> bool:
        """`True` si el deseo obliga a usar la celda."""
        return self.value == REQUEST_MAX

    def covers(self, day: int, period: int) -> bool:
        """`True` si el deseo aplica a la celda `(day, period)`."""
        if self.day is not None and self.day != day:
            return False
        return not (self.period is not None and self.period != period)


@dataclass(frozen=True, slots=True)
class UnspecifiedRequest:
    """Deseo no especificado: "N tardes libres", "un día libre cualquiera"."""

    entity_kind: EntityKind
    entity_id: str
    kind: UnspecifiedKind
    count: int = 1

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"Un deseo no especificado necesita cantidad ≥ 1: {self.count}")
