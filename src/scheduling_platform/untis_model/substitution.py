"""Sustituciones (Vertretungsplanung): calendario, ausencias y cambios del día.

El horario es semanal, pero una ausencia es de fechas concretas ("del 3 al 7 de
octubre"). Este módulo añade lo mínimo para pasar de la semana al día:

- `Holiday`: días sin clase (festivos, vacaciones, jornadas especiales).
- `Absence`: la falta de un profesor, una clase o un aula, con fechas y horas.
- `Substitution`: lo que se decide para una clase concreta de un día concreto
  (sustituir, suprimir, cambiar de aula, adelantar...), con quién la cubre.
- `SubstitutionKind`: los tipos que distingue Untis y que cuentan distinto en
  el contador de sustituciones de cada profesor.

Las fechas son cadenas `AAAAMMDD`, el mismo formato que usa Untis en sus
exports, para no perder nada al ir y volver.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from .common import EntityKind

#: Longitud de una fecha `AAAAMMDD`.
DATE_LENGTH = 8


def parse_date(value: str) -> date:
    """Convierte `AAAAMMDD` en fecha; lanza `ValueError` si no lo es."""
    texto = value.strip()
    if len(texto) != DATE_LENGTH or not texto.isdigit():
        raise ValueError(f"Fecha Untis inválida (AAAAMMDD): {value!r}")
    return date(int(texto[:4]), int(texto[4:6]), int(texto[6:]))


def format_date(value: date) -> str:
    """Convierte una fecha al formato `AAAAMMDD` de Untis."""
    return f"{value.year:04d}{value.month:02d}{value.day:02d}"


def weekday_of(value: str) -> int:
    """Día de la semana Untis (1 = lunes) de una fecha `AAAAMMDD`."""
    return parse_date(value).isoweekday()


class SubstitutionKind(StrEnum):
    """Qué se hace con una clase cuyo profesor, aula o grupo falta."""

    SUBSTITUTION = "substitution"
    """Otro profesor la da (Vertretung)."""
    SUPERVISION = "supervision"
    """Alguien cuida al grupo sin dar materia (Betreuung)."""
    CANCELLED = "cancelled"
    """La clase no se da (Entfall)."""
    ROOM = "room"
    """Solo cambia el aula (Raumvertretung)."""
    MOVED = "moved"
    """Se traslada a otra hora (Verlegung)."""
    SWAP = "swap"
    """Se intercambia con otra clase (Tausch)."""
    EXTRA = "extra"
    """Servicio extra que no viene de una ausencia (Sondereinsatz)."""


#: Cuánto suma cada tipo en el contador del profesor que la asume.
COUNTER_SIGN: dict[SubstitutionKind, int] = {
    SubstitutionKind.SUBSTITUTION: 1,
    SubstitutionKind.SUPERVISION: 1,
    SubstitutionKind.EXTRA: 1,
    SubstitutionKind.CANCELLED: 0,
    SubstitutionKind.ROOM: 0,
    SubstitutionKind.MOVED: 0,
    SubstitutionKind.SWAP: 0,
}


@dataclass(frozen=True, slots=True)
class Holiday:
    """Día o tramo sin clase: festivo, vacaciones, jornada especial."""

    id: str
    name: str = ""
    begin: str = ""
    """Fecha `AAAAMMDD` del primer día sin clase."""
    end: str = ""
    """Fecha `AAAAMMDD` del último día sin clase (incluido)."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("El festivo necesita un id")
        for campo in (self.begin, self.end):
            if campo:
                parse_date(campo)
        if self.begin and self.end and self.begin > self.end:
            raise ValueError(f"Festivo {self.id!r}: empieza después de terminar")

    @property
    def display_name(self) -> str:
        return self.name or self.id

    def covers(self, day: str) -> bool:
        """`True` si la fecha `AAAAMMDD` cae dentro del festivo."""
        inicio = self.begin or self.end
        final = self.end or self.begin
        return bool(inicio) and inicio <= day <= final


@dataclass(frozen=True, slots=True)
class Absence:
    """Falta de un profesor, una clase o un aula durante unas fechas y horas."""

    id: str
    entity_kind: EntityKind
    entity_id: str
    begin: str
    """Fecha `AAAAMMDD` del primer día de la ausencia."""
    end: str = ""
    """Último día (incluido); vacío = solo el día de `begin`."""
    first_period: int | None = None
    """Primera hora del primer día; `None` = desde el principio de la jornada."""
    last_period: int | None = None
    """Última hora del último día; `None` = hasta el final de la jornada."""
    reason: str = ""
    """Motivo tal cual lo escribe el colegio (enfermedad, curso, excursión...)."""
    text: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("La ausencia necesita un id")
        if not self.entity_id:
            raise ValueError(f"Ausencia {self.id!r} sin entidad")
        parse_date(self.begin)
        if self.end:
            parse_date(self.end)
            if self.end < self.begin:
                raise ValueError(f"Ausencia {self.id!r}: termina antes de empezar")
        for campo, valor in (
            ("first_period", self.first_period),
            ("last_period", self.last_period),
        ):
            if valor is not None and valor < 1:
                raise ValueError(f"Ausencia {self.id!r}: {campo} inválido ({valor})")
        if (
            self.first_period is not None
            and self.last_period is not None
            and self.first_period > self.last_period
            and self.last_day == self.begin
        ):
            # En una ausencia de varios días las horas acotan días distintos:
            # "del lunes a 3ª hasta el miércoles a 2ª" es correcto.
            raise ValueError(f"Ausencia {self.id!r}: la primera hora es posterior a la última")

    @property
    def last_day(self) -> str:
        """Último día de la ausencia (el de `begin` si no hay `end`)."""
        return self.end or self.begin

    def covers_day(self, day: str) -> bool:
        """`True` si la ausencia incluye esa fecha `AAAAMMDD`."""
        return self.begin <= day <= self.last_day

    def covers(self, day: str, period: int) -> bool:
        """`True` si la ausencia incluye esa hora de esa fecha.

        Las horas solo acotan el primer y el último día: una ausencia de varios
        días es completa en los días de en medio, como en Untis.
        """
        if not self.covers_day(day):
            return False
        if self.first_period is not None and day == self.begin and period < self.first_period:
            return False
        return not (
            self.last_period is not None and day == self.last_day and period > self.last_period
        )


@dataclass(frozen=True, slots=True)
class Substitution:
    """Decisión tomada para una clase de un día concreto."""

    id: str
    date: str
    """Fecha `AAAAMMDD` del día afectado."""
    period: int
    lesson_number: int
    kind: SubstitutionKind = SubstitutionKind.SUBSTITUTION
    absent_teacher: str = ""
    """Profesor que falta (vacío si no viene de una ausencia de profesor)."""
    teacher: str = ""
    """Profesor que la asume; vacío si aún no hay nadie o la clase se suprime."""
    room: str = ""
    """Aula nueva, si cambia."""
    absence: str = ""
    """Id de la ausencia que la provoca, si viene de una."""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("La sustitución necesita un id")
        parse_date(self.date)
        if self.period < 1:
            raise ValueError(f"Sustitución {self.id!r}: hora inválida ({self.period})")

    @property
    def counts(self) -> int:
        """Cuánto suma en el contador del profesor que la asume."""
        return COUNTER_SIGN[self.kind] if self.teacher else 0

    @property
    def open(self) -> bool:
        """`True` si aún hay que decidir quién la cubre."""
        return not self.teacher and self.kind in (
            SubstitutionKind.SUBSTITUTION,
            SubstitutionKind.SUPERVISION,
        )
