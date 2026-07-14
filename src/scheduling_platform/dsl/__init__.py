"""Constraint DSL (Fase 3).

Lenguaje declarativo con el que los plugins definen restricciones como
expresiones algebraicas componibles. Se compila a ``ISolver`` (y, desde la
Fase 4, pasando por el CIR). No conoce ningún solver concreto: prohibido
importar ``ortools`` aquí.
"""

from __future__ import annotations

from .compiler import DslToSolverCompiler
from .domain import BoolDomain, Domain, IntDomain
from .exceptions import DslError, UnsupportedConstraintError
from .expressions import DslRelOp, LinearExpr, Relation, Var
from .logic import (
    AllDifferentConstraint,
    BoolOrConstraint,
    DslConstraint,
    DslLiteral,
    ImplicationConstraint,
    IntervalSpec,
    LinearConstraint,
    NoOverlapConstraint,
)
from .model import DslModel, Objective

__all__ = [
    "AllDifferentConstraint",
    "BoolDomain",
    "BoolOrConstraint",
    "Domain",
    "DslConstraint",
    "DslError",
    "DslLiteral",
    "DslModel",
    "DslRelOp",
    "DslToSolverCompiler",
    "ImplicationConstraint",
    "IntDomain",
    "IntervalSpec",
    "LinearConstraint",
    "LinearExpr",
    "NoOverlapConstraint",
    "Objective",
    "Relation",
    "UnsupportedConstraintError",
    "Var",
]
