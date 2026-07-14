"""Modelo del DSL: contenedor de restricciones y objetivo.

Es lo que el compilador (o, desde la Fase 4, el lowering a CIR) consume. El
objetivo se expresa como una :class:`~scheduling_platform.dsl.expressions.LinearExpr`
a minimizar (las restricciones blandas se traducen a variables de holgura
penalizadas en la Fase 8).
"""

from __future__ import annotations

from dataclasses import dataclass

from .expressions import LinearExpr, Var
from .logic import DslConstraint


@dataclass(frozen=True, slots=True)
class Objective:
    """Función objetivo. Por ahora solo minimización."""

    expr: LinearExpr
    sense: str = "minimize"


@dataclass(frozen=True, slots=True)
class DslModel:
    """Conjunto de restricciones y (opcionalmente) un objetivo."""

    constraints: tuple[DslConstraint, ...]
    objective: Objective | None = None

    def variables(self) -> frozenset[Var]:
        result: set[Var] = set()
        for constraint in self.constraints:
            result |= constraint.variables()
        if self.objective is not None:
            result |= self.objective.expr.variables()
        return frozenset(result)
