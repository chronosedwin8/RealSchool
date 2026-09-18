"""Horario (Stundenplan): el resultado, en vocabulario Untis.

Un proyecto guarda varias versiones de horario; cada una lleva su número de
evaluación y el desglose por criterio que alimenta la ventana de Evaluación.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .weighting import UNPLACED_PENALTY


@dataclass(frozen=True, slots=True)
class Assignment:
    """Una línea de lección colocada en una celda concreta."""

    lesson_number: int
    line: int
    day: int
    period: int
    room: str | None = None
    fixed: bool = False
    manual: bool = False
    """`True` si la colocó el usuario en el Diálogo de planificación."""

    def __post_init__(self) -> None:
        if self.line < 0:
            raise ValueError(f"Lección {self.lesson_number}: línea negativa")
        if self.day < 1 or self.period < 1:
            raise ValueError(
                f"Lección {self.lesson_number}: celda inválida "
                f"(día={self.day}, período={self.period})"
            )

    @property
    def slot(self) -> tuple[int, int]:
        """La celda `(día, período)`."""
        return (self.day, self.period)


@dataclass(frozen=True, slots=True)
class CriterionScore:
    """Contribución de un criterio al número de evaluación."""

    criterion: str
    violations: int
    weight: int

    @property
    def points(self) -> int:
        """Puntos que este criterio aporta a la evaluación."""
        return self.violations * self.weight


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Número de evaluación y su desglose, como la ventana de Untis."""

    unplaced_periods: int = 0
    clashes: int = 0
    scores: tuple[CriterionScore, ...] = field(default_factory=tuple)

    @property
    def soft_points(self) -> int:
        """Suma ponderada de las violaciones blandas."""
        return sum(s.points for s in self.scores)

    @property
    def total(self) -> int:
        """Número de evaluación; los períodos sin colocar dominan."""
        return self.soft_points + self.unplaced_periods * UNPLACED_PENALTY

    def by_contribution(self) -> tuple[CriterionScore, ...]:
        """Criterios ordenados de mayor a menor contribución."""
        return tuple(sorted(self.scores, key=lambda s: (-s.points, s.criterion)))


@dataclass(frozen=True, slots=True)
class Timetable:
    """Una versión de horario del proyecto."""

    id: str
    name: str = ""
    assignments: tuple[Assignment, ...] = field(default_factory=tuple)
    evaluation: Evaluation = field(default_factory=Evaluation)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("El horario necesita un id")

    @property
    def display_name(self) -> str:
        return self.name or self.id

    def by_lesson(self) -> dict[int, tuple[Assignment, ...]]:
        """Asignaciones agrupadas por número de lección."""
        agrupado: defaultdict[int, list[Assignment]] = defaultdict(list)
        for a in self.assignments:
            agrupado[a.lesson_number].append(a)
        return {k: tuple(v) for k, v in agrupado.items()}

    def placed_periods(self, lesson_number: int, line: int = 0) -> int:
        """Cuántos períodos tiene colocados esa línea."""
        return sum(
            1 for a in self.assignments if a.lesson_number == lesson_number and a.line == line
        )
