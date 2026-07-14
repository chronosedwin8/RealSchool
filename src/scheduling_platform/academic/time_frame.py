"""Marco horario académico y su mapeo con la rejilla canónica.

Un :class:`TimeFrame` describe la estructura semanal en términos humanos
(días por períodos) y sabe traducir entre ``(día, período)`` y el índice lineal
de slot del Modelo Canónico (ADR-004/006). Cada día se corresponde con un
segmento de la rejilla, de modo que una clase de varios períodos no cruza el
límite del día.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.exceptions import require
from ..core.ids import TimeSlotIndex
from ..core.time_grid import TimeGrid
from .exceptions import InvalidTimeFrame


@dataclass(frozen=True, slots=True)
class TimeFrame:
    """Estructura semanal uniforme: ``len(day_names)`` días de ``periods_per_day``."""

    day_names: tuple[str, ...]
    periods_per_day: int

    def __post_init__(self) -> None:
        require(len(self.day_names) >= 1, InvalidTimeFrame, "el marco necesita >= 1 día")
        require(
            self.periods_per_day >= 1,
            InvalidTimeFrame,
            f"periods_per_day < 1: {self.periods_per_day}",
        )

    @property
    def num_days(self) -> int:
        return len(self.day_names)

    def to_grid(self) -> TimeGrid:
        """Rejilla canónica: un segmento por día, cada uno con ``periods_per_day`` slots."""
        return TimeGrid.from_segment_lengths([self.periods_per_day] * self.num_days)

    def slot_of(self, day: int, period: int) -> TimeSlotIndex:
        """Índice de slot lineal para el ``(día, período)`` dado."""
        require(0 <= day < self.num_days, InvalidTimeFrame, f"día fuera de rango: {day}")
        require(
            0 <= period < self.periods_per_day,
            InvalidTimeFrame,
            f"período fuera de rango: {period}",
        )
        return TimeSlotIndex(day * self.periods_per_day + period)

    def decode(self, slot: TimeSlotIndex) -> tuple[int, int]:
        """``(día, período)`` correspondiente a un índice de slot lineal."""
        require(
            0 <= slot < self.num_days * self.periods_per_day,
            InvalidTimeFrame,
            f"slot fuera del marco: {slot}",
        )
        day, period = divmod(int(slot), self.periods_per_day)
        return day, period
