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
