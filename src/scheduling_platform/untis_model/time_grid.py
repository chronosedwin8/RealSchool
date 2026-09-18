"""Rejilla de tiempo (Zeitraster).

Un proyecto tiene varias rejillas —el Colegio Alemán usa ocho— y cada clase
apunta a una. Las horas de reloj de un período no cambian con el día dentro de
una misma rejilla (verificado sobre el export real), así que `periods` se indexa
solo por número de período.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import HalfDay, PeriodKind


def minutes_to_hhmm(minutes: int) -> str:
    """Convierte minutos desde medianoche al formato `HHMM` de Untis."""
    return f"{minutes // 60:02d}{minutes % 60:02d}"


def hhmm_to_minutes(value: str) -> int:
    """Convierte `HHMM` (formato Untis) a minutos desde medianoche."""
    texto = value.strip()
    if not texto.isdigit() or len(texto) not in (3, 4):
        raise ValueError(f"Hora Untis inválida: {value!r}")
    texto = texto.zfill(4)
    horas, mins = int(texto[:2]), int(texto[2:])
    if not (0 <= horas <= 23 and 0 <= mins <= 59):
        raise ValueError(f"Hora Untis fuera de rango: {value!r}")
    return horas * 60 + mins


@dataclass(frozen=True, slots=True)
class PeriodDef:
    """Un período de la rejilla: número, horas de reloj y tipo."""

    number: int
    start: int
    """Minutos desde medianoche."""
    end: int
    """Minutos desde medianoche."""
    kind: PeriodKind = PeriodKind.LESSON
    half_day: HalfDay = HalfDay.MORNING
    name: str = ""

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError(f"El número de período empieza en 1: {self.number}")
        if not 0 <= self.start < 24 * 60:
            raise ValueError(f"Hora de inicio fuera del día: {self.start}")
        if self.end <= self.start:
            raise ValueError(f"El período {self.number} termina antes de empezar")

    @property
    def duration(self) -> int:
        """Duración en minutos."""
        return self.end - self.start

    @property
    def is_teaching(self) -> bool:
        """`True` si es un período lectivo (no un recreo)."""
        return self.kind is PeriodKind.LESSON


@dataclass(frozen=True, slots=True)
class TimeGrid:
    """Rejilla de tiempo de una sección."""

    id: str
    name: str = ""
    days: tuple[int, ...] = (1, 2, 3, 4, 5)
    periods: tuple[PeriodDef, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("La rejilla necesita un id")
        if not self.days:
            raise ValueError(f"Rejilla {self.id!r} sin días")
        if any(d < 1 for d in self.days):
            raise ValueError(f"Rejilla {self.id!r}: los días empiezan en 1: {self.days}")
        if len(set(self.days)) != len(self.days):
            raise ValueError(f"Rejilla {self.id!r} con días repetidos: {self.days}")
        numeros = [p.number for p in self.periods]
        if len(set(numeros)) != len(numeros):
            raise ValueError(f"Rejilla {self.id!r} con períodos repetidos: {numeros}")

    @property
    def display_name(self) -> str:
        """Nombre legible; cae al id si la rejilla no tiene nombre propio."""
        return self.name or self.id

    @property
    def teaching_periods(self) -> tuple[PeriodDef, ...]:
        """Períodos lectivos, en orden."""
        return tuple(p for p in sorted(self.periods, key=lambda p: p.number) if p.is_teaching)

    def period(self, number: int) -> PeriodDef | None:
        """Devuelve el período `number`, o `None` si la rejilla no lo define."""
        for p in self.periods:
            if p.number == number:
                return p
        return None

    def slots(self) -> tuple[tuple[int, int], ...]:
        """Todas las celdas lectivas `(día, período)` de la rejilla."""
        return tuple((d, p.number) for d in sorted(self.days) for p in self.teaching_periods)
