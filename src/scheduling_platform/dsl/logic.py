"""Restricciones del DSL: lo que un plugin emite.

Cuatro formas cubren la Fase 3, todas con una bajada directa y probada a
``ISolver``:

- :class:`LinearConstraint` — una :class:`Relation` lineal que debe cumplirse.
- :class:`AllDifferentConstraint` — todas las variables toman valores distintos.
- :class:`BoolOrConstraint` — al menos un literal es verdadero.
- :class:`ImplicationConstraint` — ``antecedente -> consecuente``.

Formas más ricas (Or/And/Not anidados, NoOverlap, consecutividad, reificación
general) se añadirán en la Fase 4 (CIR + pases) junto con su bajada.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .domain import BoolDomain
from .exceptions import DslError
from .expressions import Relation, Var


@dataclass(frozen=True, slots=True)
class DslLiteral:
    """Literal booleano: una variable de dominio booleano o su negación."""

    var: Var
    positive: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.var, Var) or not isinstance(self.var.domain, BoolDomain):
            raise DslError(f"un literal requiere una variable booleana: {self.var}")

    def __invert__(self) -> DslLiteral:
        return DslLiteral(self.var, not self.positive)


class DslConstraint(ABC):
    """Base de las restricciones que el compilador sabe bajar a ``ISolver``."""

    @abstractmethod
    def variables(self) -> frozenset[Var]:
        """Variables involucradas en la restricción."""


@dataclass(frozen=True, slots=True)
class LinearConstraint(DslConstraint):
    relation: Relation

    def variables(self) -> frozenset[Var]:
        return self.relation.variables()


@dataclass(frozen=True, slots=True)
class AllDifferentConstraint(DslConstraint):
    variables_: tuple[Var, ...]

    def __post_init__(self) -> None:
        if len(self.variables_) < 2:
            raise DslError("all_different requiere >= 2 variables")

    def variables(self) -> frozenset[Var]:
        return frozenset(self.variables_)


@dataclass(frozen=True, slots=True)
class BoolOrConstraint(DslConstraint):
    literals: tuple[DslLiteral, ...]

    def __post_init__(self) -> None:
        if len(self.literals) < 1:
            raise DslError("bool_or requiere >= 1 literal")

    def variables(self) -> frozenset[Var]:
        return frozenset(lit.var for lit in self.literals)


@dataclass(frozen=True, slots=True)
class ImplicationConstraint(DslConstraint):
    antecedent: DslLiteral
    consequent: DslLiteral

    def variables(self) -> frozenset[Var]:
        return frozenset({self.antecedent.var, self.consequent.var})


@dataclass(frozen=True, slots=True)
class IntervalSpec:
    """Un intervalo ``[start, start + size)``, opcionalmente condicionado.

    ``presence`` es el literal que decide si el intervalo existe (p. ej. "la
    tarea usa este recurso"); ``None`` significa siempre presente.
    """

    start: Var
    size: int
    presence: DslLiteral | None = None

    def __post_init__(self) -> None:
        if self.size < 1:
            raise DslError(f"tamaño de intervalo < 1: {self.size}")

    def variables(self) -> frozenset[Var]:
        if self.presence is None:
            return frozenset({self.start})
        return frozenset({self.start, self.presence.var})


@dataclass(frozen=True, slots=True)
class NoOverlapConstraint(DslConstraint):
    """Los intervalos presentes no pueden solaparse en el tiempo.

    Es la formulación compacta del "un recurso, una tarea a la vez": en vez de
    una variable de ocupación por período, basta un intervalo por par
    (tarea, recurso).
    """

    intervals: tuple[IntervalSpec, ...]

    def __post_init__(self) -> None:
        if len(self.intervals) < 2:
            raise DslError("no_overlap requiere >= 2 intervalos")

    def variables(self) -> frozenset[Var]:
        result: set[Var] = set()
        for interval in self.intervals:
            result |= interval.variables()
        return frozenset(result)
