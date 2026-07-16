"""Rejilla temporal discreta con segmentos (D1, ADR-004).

El tiempo se modela como una secuencia lineal de *slots* atómicos indexados
por entero ``0..horizon-1``. La rejilla se particiona en :class:`Segment`
contiguos que representan fronteras naturales (p. ej. un "día", un turno o una
jornada). Dos slots solo son *contiguos* si son adyacentes y pertenecen al
mismo segmento; esto permite, de forma agnóstica al dominio, que una tarea de
varios slots no cruce una frontera natural.

El núcleo no conoce el concepto de "día": el mapeo ``(día, período) <-> índice``
lo realiza el adaptador académico en la Fase 2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

from .exceptions import InvalidTimeGrid, require
from .ids import TimeSlotIndex


@cache
def _valid_starts(
    segments: tuple[Segment, ...], horizon: int, duration: int, same_segment: bool
) -> frozenset[TimeSlotIndex]:
    """Inicios válidos memoizados por (rejilla, duración, same_segment).

    ``context.build`` pide esto una vez por tarea y casi todas comparten
    ``(duration, same_segment)``; recalcularlo dominaba la construcción del modelo
    en instituciones grandes (perfilado en O10). La rejilla es inmutable y
    hashable, así que memoizar es seguro.
    """
    starts: set[TimeSlotIndex] = set()
    if same_segment:
        for seg in segments:
            last = seg.end - duration
            for i in range(seg.start, last + 1):
                starts.add(TimeSlotIndex(i))
    else:
        for i in range(horizon - duration + 1):
            starts.add(TimeSlotIndex(i))
    return frozenset(starts)


@dataclass(frozen=True, slots=True)
class Segment:
    """Rango contiguo de slots que constituye una frontera natural.

    ``start`` es el índice del primer slot (inclusive) y ``length`` el número
    de slots; el final ``end`` es exclusivo.
    """

    id: int
    start: TimeSlotIndex
    length: int

    def __post_init__(self) -> None:
        require(self.id >= 0, InvalidTimeGrid, f"id de segmento negativo: {self.id}")
        require(self.start >= 0, InvalidTimeGrid, f"start de segmento negativo: {self.start}")
        require(self.length >= 1, InvalidTimeGrid, f"length de segmento < 1: {self.length}")

    @property
    def end(self) -> TimeSlotIndex:
        """Índice del slot siguiente al último (exclusivo)."""
        return TimeSlotIndex(self.start + self.length)

    def contains(self, index: TimeSlotIndex) -> bool:
        return self.start <= index < self.end


@dataclass(frozen=True, slots=True)
class TimeSlot:
    """Vista materializada de un slot: su índice y el segmento al que pertenece."""

    index: TimeSlotIndex
    segment_id: int


@dataclass(frozen=True, slots=True)
class TimeGrid:
    """Universo temporal discreto formado por segmentos contiguos sin huecos."""

    segments: tuple[Segment, ...]

    def __post_init__(self) -> None:
        require(len(self.segments) >= 1, InvalidTimeGrid, "la rejilla necesita >= 1 segmento")
        require(
            self.segments[0].start == 0, InvalidTimeGrid, "el primer segmento debe iniciar en 0"
        )
        seen_ids: set[int] = set()
        cursor: int = 0
        for seg in self.segments:
            require(
                seg.start == cursor,
                InvalidTimeGrid,
                f"segmentos no contiguos: se esperaba start={cursor}, llegó {seg.start}",
            )
            require(seg.id not in seen_ids, InvalidTimeGrid, f"id de segmento duplicado: {seg.id}")
            seen_ids.add(seg.id)
            cursor = seg.end

    @classmethod
    def from_segment_lengths(cls, lengths: Sequence[int]) -> TimeGrid:
        """Construye la rejilla a partir de la longitud de cada segmento.

        Ejemplo: ``from_segment_lengths([3, 3])`` -> 2 segmentos de 3 slots
        (6 slots en total), como 2 "días" de 3 períodos.
        """
        require(len(lengths) >= 1, InvalidTimeGrid, "se requiere >= 1 segmento")
        segments: list[Segment] = []
        start = 0
        for i, length in enumerate(lengths):
            segments.append(Segment(id=i, start=TimeSlotIndex(start), length=length))
            start += length
        return cls(segments=tuple(segments))

    @property
    def horizon(self) -> int:
        """Número total de slots de la rejilla."""
        return sum(seg.length for seg in self.segments)

    def __contains__(self, index: int) -> bool:
        return 0 <= index < self.horizon

    def segment_of(self, index: TimeSlotIndex) -> Segment:
        """Segmento que contiene ``index`` (lanza si está fuera de la rejilla)."""
        for seg in self.segments:
            if seg.contains(index):
                return seg
        raise InvalidTimeGrid(
            f"el slot {index} está fuera de la rejilla (horizonte={self.horizon})"
        )

    def slot(self, index: TimeSlotIndex) -> TimeSlot:
        return TimeSlot(index=index, segment_id=self.segment_of(index).id)

    def are_contiguous(self, a: TimeSlotIndex, b: TimeSlotIndex) -> bool:
        """``True`` si ``b`` sigue inmediatamente a ``a`` dentro del mismo segmento."""
        return b == a + 1 and self.segment_of(a).id == self.segment_of(b).id

    def valid_starts(self, duration: int, same_segment: bool) -> frozenset[TimeSlotIndex]:
        """Slots de inicio en los que cabe una tarea de ``duration`` slots.

        Si ``same_segment`` es ``True``, la tarea debe caber íntegra dentro de
        un único segmento; en caso contrario puede abarcar cualquier tramo
        contiguo del horizonte. Reutilizado por el modelo CP-SAT (Fase 7).
        """
        require(duration >= 1, InvalidTimeGrid, f"duración < 1: {duration}")
        return _valid_starts(self.segments, self.horizon, duration, same_segment)
