"""Vigilancia de recreos (Pausenaufsichten): zonas y turnos de guardia.

Una guardia es un turno: una **zona** (patio, pasillo, comedor...) vigilada por
un profesor durante un **recreo** concreto de la rejilla de tiempo. Untis las
llama "Aufsichten", a las zonas "Aufsichtsbereiche" (los pasillos, "Gänge") y
limita cuántos minutos de guardia puede tener cada profesor a la semana
("PA-Max", aquí `Teacher.supervision_max`).

El turno se identifica por `(zona, día, recreo)`: en una misma zona y recreo no
hay dos turnos el mismo día. `teacher` vacío es un turno **sin asignar**, que es
lo que reparte la generación de guardias.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SupervisionArea:
    """Zona que hay que vigilar durante los recreos."""

    id: str
    name: str = ""
    time_grid: str = ""
    """Rejilla cuyos recreos se vigilan (vacío = la primera del proyecto)."""
    weight: int = 1
    """Importancia de la zona 0-5: cuánto cuesta dejarla sin vigilar."""
    text: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("La zona de vigilancia necesita un id")
        if not 0 <= self.weight <= 5:
            raise ValueError(f"Zona {self.id!r}: peso fuera de 0-5: {self.weight}")

    @property
    def display_name(self) -> str:
        return self.name or self.id


@dataclass(frozen=True, slots=True)
class Supervision:
    """Un turno de guardia: zona, día y recreo, con su profesor si ya está puesto."""

    area: str
    day: int
    period: int
    """Número del período de recreo en la rejilla."""
    teacher: str = ""
    """Id del profesor; vacío si el turno está sin asignar."""
    fixed: bool = False
    """`True` si lo puso una persona y la generación no debe moverlo."""
    minutes: int = 0
    """Duración del turno; 0 = la del recreo en la rejilla."""

    def __post_init__(self) -> None:
        if not self.area:
            raise ValueError("El turno de guardia necesita una zona")
        if self.day < 1:
            raise ValueError(f"Día inválido en la guardia de {self.area!r}: {self.day}")
        if self.period < 1:
            raise ValueError(f"Recreo inválido en la guardia de {self.area!r}: {self.period}")
        if self.minutes < 0:
            raise ValueError(f"Guardia de {self.area!r} con minutos negativos")

    @property
    def slot(self) -> tuple[int, int]:
        """Celda `(día, recreo)` del turno."""
        return (self.day, self.period)

    @property
    def key(self) -> tuple[str, int, int]:
        """Identidad del turno: zona, día y recreo."""
        return (self.area, self.day, self.period)

    @property
    def assigned(self) -> bool:
        """`True` si el turno ya tiene profesor."""
        return bool(self.teacher)
