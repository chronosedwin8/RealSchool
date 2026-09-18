"""Reloj común: el universo de minutos donde se miden los choques reales.

Las rejillas de un colegio no comparten horas: el período 5 de Primaria
(09:15-10:00) no coincide con el período 5 de Bachillerato (09:35-09:55). Un
profesor que da clase en ambas choca o no según el **reloj**, no según el número
de período. Por eso el modelo canónico usa slots de un minuto sobre la unión de
todas las rejillas —el mismo enfoque validado en ADR-016/017—, y cada rejilla
Untis se proyecta sobre ese reloj común.
"""

from __future__ import annotations

from dataclasses import dataclass

from scheduling_platform.untis_model import TimeGrid, UntisProject


@dataclass(frozen=True, slots=True)
class Clock:
    """Codifica `(día, minuto)` <-> slot canónico.

    Un segmento por día, de `day_start` a `day_end` minutos. Los días se
    numeran como en Untis (1 = lunes) y se compactan en `days`, en orden.
    """

    days: tuple[int, ...]
    day_start: int
    day_end: int

    def __post_init__(self) -> None:
        if not self.days:
            raise ValueError("El reloj necesita al menos un día")
        if self.day_end <= self.day_start:
            raise ValueError("El reloj termina antes de empezar")

    @property
    def day_length(self) -> int:
        """Minutos por día del reloj (longitud de cada segmento)."""
        return self.day_end - self.day_start

    @property
    def horizon(self) -> int:
        return self.day_length * len(self.days)

    def slot(self, day: int, minute: int) -> int:
        """Slot canónico del minuto `minute` del día Untis `day`."""
        indice = self.days.index(day)
        if not self.day_start <= minute < self.day_end:
            raise ValueError(f"Minuto {minute} fuera del reloj [{self.day_start}, {self.day_end})")
        return indice * self.day_length + (minute - self.day_start)

    def decode(self, slot: int) -> tuple[int, int]:
        """`(día Untis, minuto)` de un slot canónico."""
        indice, offset = divmod(slot, self.day_length)
        return self.days[indice], self.day_start + offset

    @classmethod
    def of(cls, grids: tuple[TimeGrid, ...]) -> Clock:
        """Reloj mínimo que contiene todas las rejillas."""
        periodos = [p for g in grids for p in g.periods]
        if not periodos:
            raise ValueError("No hay períodos: no se puede construir el reloj")
        dias = tuple(sorted({d for g in grids for d in g.days}))
        return cls(
            days=dias,
            day_start=min(p.start for p in periodos),
            day_end=max(p.end for p in periodos),
        )

    @classmethod
    def of_project(cls, project: UntisProject) -> Clock:
        return cls.of(project.time_grids)
