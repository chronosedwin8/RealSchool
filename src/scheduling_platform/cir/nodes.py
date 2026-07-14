"""Nodos de la Constraint Intermediate Representation (CIR).

Representación canónica, hashable y agnóstica del solver del problema de
optimización. Las variables se referencian por su ``key`` (str) y sus dominios
se guardan aparte en el :class:`CirModel`. La forma canónica (términos
ordenados sin ceros, claves ordenadas) hace que dos restricciones
estructuralmente idénticas sean *iguales*, lo que habilita la deduplicación y
el análisis por los pases de optimización.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..dsl.domain import Domain
from ..sal.interface import RelOp


@dataclass(frozen=True, slots=True)
class CirLiteral:
    """Literal booleano del CIR: una key o su negación."""

    key: str
    positive: bool = True

    def __invert__(self) -> CirLiteral:
        return CirLiteral(self.key, not self.positive)


class CirConstraint(ABC):
    """Base de las restricciones del CIR."""

    @abstractmethod
    def variables(self) -> frozenset[str]:
        """Keys de las variables involucradas."""


@dataclass(frozen=True, slots=True)
class CirLinear(CirConstraint):
    """Restricción lineal canónica ``sum(coef * key) op rhs``."""

    terms: tuple[tuple[str, int], ...]
    op: RelOp
    rhs: int

    @staticmethod
    def make(terms: tuple[tuple[str, int], ...], op: RelOp, rhs: int) -> CirLinear:
        acc: dict[str, int] = {}
        for key, coef in terms:
            acc[key] = acc.get(key, 0) + coef
        canonical = tuple(sorted(((k, c) for k, c in acc.items() if c != 0), key=lambda p: p[0]))
        return CirLinear(canonical, op, rhs)

    def variables(self) -> frozenset[str]:
        return frozenset(key for key, _ in self.terms)


@dataclass(frozen=True, slots=True)
class CirAllDifferent(CirConstraint):
    keys: tuple[str, ...]

    def variables(self) -> frozenset[str]:
        return frozenset(self.keys)


@dataclass(frozen=True, slots=True)
class CirBoolOr(CirConstraint):
    literals: tuple[CirLiteral, ...]

    def variables(self) -> frozenset[str]:
        return frozenset(lit.key for lit in self.literals)


@dataclass(frozen=True, slots=True)
class CirImplication(CirConstraint):
    antecedent: CirLiteral
    consequent: CirLiteral

    def variables(self) -> frozenset[str]:
        return frozenset({self.antecedent.key, self.consequent.key})


@dataclass(frozen=True, slots=True)
class CirIntervalSpec:
    """Intervalo ``[start, start + size)`` con presencia opcional."""

    start_key: str
    size: int
    presence: CirLiteral | None = None

    def variables(self) -> frozenset[str]:
        if self.presence is None:
            return frozenset({self.start_key})
        return frozenset({self.start_key, self.presence.key})


@dataclass(frozen=True, slots=True)
class CirNoOverlap(CirConstraint):
    """Los intervalos presentes no se solapan (formulación compacta)."""

    intervals: tuple[CirIntervalSpec, ...]

    def variables(self) -> frozenset[str]:
        result: set[str] = set()
        for interval in self.intervals:
            result |= interval.variables()
        return frozenset(result)


@dataclass(frozen=True, slots=True)
class CirObjective:
    """Función objetivo lineal a minimizar."""

    terms: tuple[tuple[str, int], ...]
    constant: int = 0


@dataclass(frozen=True, slots=True)
class CirModel:
    """Modelo CIR completo: variables (con dominio), restricciones y objetivo."""

    variables: tuple[tuple[str, Domain], ...]
    constraints: tuple[CirConstraint, ...]
    objective: CirObjective | None = None

    def domain_of(self, key: str) -> Domain:
        for var_key, domain in self.variables:
            if var_key == key:
                return domain
        raise KeyError(f"variable no declarada en el CIR: {key}")

    def variable_keys(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.variables)

    def with_constraints(self, constraints: tuple[CirConstraint, ...]) -> CirModel:
        """Devuelve una copia con otras restricciones (usado por los pases)."""
        return CirModel(self.variables, constraints, self.objective)
