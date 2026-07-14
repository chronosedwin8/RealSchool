"""Solver Abstraction Layer: la interfaz ``ISolver`` (Prompt3 §2.2).

Contrato mínimo, agnóstico de proveedor, con el que el resto del sistema habla
al solver. Las variables son *handles opacos* (``SolverVar``, un entero): cada
implementación concreta mantiene su propio mapeo interno de handle a variable
nativa, de modo que ninguna capa superior ve tipos de OR-Tools. ``ISolver`` es
la ÚNICA frontera autorizada a conocer un solver concreto; ``ORToolsSolver``
llegará en la Fase 7 y otro solver (Gurobi, Choco) podría sustituirlo sin
tocar el dominio.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import NewType

SolverVar = NewType("SolverVar", int)
"""Handle opaco de una variable del solver (índice entero)."""


class RelOp(Enum):
    """Operadores relacionales canónicos que el solver entiende directamente."""

    LE = "<="
    GE = ">="
    EQ = "=="


class SolverStatus(Enum):
    """Resultado de una invocación a ``solve``."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    MODEL_INVALID = "model_invalid"


@dataclass(frozen=True, slots=True)
class Literal:
    """Un literal booleano: una variable o su negación."""

    var: SolverVar
    positive: bool = True

    def negated(self) -> Literal:
        return Literal(self.var, not self.positive)


@dataclass(frozen=True, slots=True)
class SolverConfig:
    """Parámetros de búsqueda expuestos por el solver (telemetría/determinismo).

    ``None`` deja el valor por defecto del solver. ``random_seed`` fijo habilita
    ejecuciones reproducibles (verificado en la Fase 7).
    """

    max_time_in_seconds: float | None = None
    num_search_workers: int | None = None
    random_seed: int | None = None


class ISolver(ABC):
    """Interfaz pura de un solver de restricciones."""

    @abstractmethod
    def new_bool_var(self, name: str) -> SolverVar:
        """Crea una variable booleana y devuelve su handle."""

    @abstractmethod
    def new_int_var(self, lo: int, hi: int, name: str) -> SolverVar:
        """Crea una variable entera en ``[lo, hi]`` y devuelve su handle."""

    @abstractmethod
    def add_linear(self, terms: Sequence[tuple[SolverVar, int]], op: RelOp, rhs: int) -> None:
        """Publica ``sum(coef_i * var_i) op rhs``."""

    @abstractmethod
    def add_all_different(self, variables: Sequence[SolverVar]) -> None:
        """Publica que todas las variables tomen valores distintos."""

    @abstractmethod
    def add_bool_or(self, literals: Sequence[Literal]) -> None:
        """Publica que al menos un literal sea verdadero."""

    @abstractmethod
    def add_implication(self, antecedent: Literal, consequent: Literal) -> None:
        """Publica ``antecedent -> consequent``."""

    @abstractmethod
    def minimize(self, terms: Sequence[tuple[SolverVar, int]], constant: int = 0) -> None:
        """Fija la función objetivo a minimizar: ``sum(coef_i * var_i) + constant``."""

    @abstractmethod
    def solve(self, config: SolverConfig | None = None) -> SolverStatus:
        """Ejecuta la optimización y devuelve el estado."""

    @abstractmethod
    def value(self, var: SolverVar) -> int:
        """Valor de una variable en la última solución (tras ``solve``)."""

    @abstractmethod
    def objective_value(self) -> int:
        """Valor de la función objetivo en la última solución."""
