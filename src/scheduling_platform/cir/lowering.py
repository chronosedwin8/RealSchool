"""Lowering DSL -> CIR.

Traduce un :class:`~scheduling_platform.dsl.model.DslModel` a un
:class:`~scheduling_platform.cir.nodes.CirModel`, normalizando las relaciones
a la forma canónica ``sum(coef*key) op rhs`` con ``op`` en {LE, GE, EQ}
(``<``/``>`` se convierten usando la integralidad de las variables).
"""

from __future__ import annotations

from ..dsl.domain import Domain
from ..dsl.expressions import DslRelOp, LinearExpr, Relation
from ..dsl.logic import (
    AllDifferentConstraint,
    BoolOrConstraint,
    DslConstraint,
    DslLiteral,
    ImplicationConstraint,
    IntervalSpec,
    LinearConstraint,
    NoOverlapConstraint,
)
from ..dsl.model import DslModel
from ..sal.interface import RelOp
from .exceptions import CirError
from .nodes import (
    CirAllDifferent,
    CirBoolOr,
    CirConstraint,
    CirImplication,
    CirIntervalSpec,
    CirLinear,
    CirLiteral,
    CirModel,
    CirNoOverlap,
    CirObjective,
)


def lower(model: DslModel) -> CirModel:
    """Baja un modelo del DSL a su representación intermedia (CIR)."""
    variables = _collect_variables(model)
    constraints = tuple(_lower_constraint(c) for c in model.constraints)
    objective = _lower_objective(model.objective.expr) if model.objective is not None else None
    return CirModel(variables, constraints, objective)


def _collect_variables(model: DslModel) -> tuple[tuple[str, Domain], ...]:
    by_key: dict[str, Domain] = {}
    for var in model.variables():
        existing = by_key.get(var.key)
        if existing is not None and existing != var.domain:
            raise CirError(f"la key de variable '{var.key}' se usa con dominios distintos")
        by_key[var.key] = var.domain
    return tuple(sorted(by_key.items(), key=lambda pair: pair[0]))


def _lower_constraint(constraint: DslConstraint) -> CirConstraint:
    if isinstance(constraint, LinearConstraint):
        return _lower_relation(constraint.relation)
    if isinstance(constraint, AllDifferentConstraint):
        keys = tuple(sorted(v.key for v in constraint.variables_))
        return CirAllDifferent(keys)
    if isinstance(constraint, BoolOrConstraint):
        return CirBoolOr(tuple(_lower_literal(lit) for lit in constraint.literals))
    if isinstance(constraint, ImplicationConstraint):
        return CirImplication(
            _lower_literal(constraint.antecedent), _lower_literal(constraint.consequent)
        )
    if isinstance(constraint, NoOverlapConstraint):
        return CirNoOverlap(tuple(_lower_interval(i) for i in constraint.intervals))
    raise CirError(
        f"restricción DSL no soportada por el lowering: {constraint!r}"
    )  # pragma: no cover


def _lower_literal(literal: DslLiteral) -> CirLiteral:
    return CirLiteral(literal.var.key, literal.positive)


def _lower_interval(interval: IntervalSpec) -> CirIntervalSpec:
    return CirIntervalSpec(
        start_key=interval.start.key,
        size=interval.size,
        presence=None if interval.presence is None else _lower_literal(interval.presence),
    )


def _lower_relation(relation: Relation) -> CirLinear:
    terms = tuple((var.key, coef) for var, coef in relation.expr.coeffs)
    rhs = -relation.expr.constant
    match relation.op:
        case DslRelOp.LE:
            return CirLinear.make(terms, RelOp.LE, rhs)
        case DslRelOp.GE:
            return CirLinear.make(terms, RelOp.GE, rhs)
        case DslRelOp.EQ:
            return CirLinear.make(terms, RelOp.EQ, rhs)
        case DslRelOp.LT:
            return CirLinear.make(terms, RelOp.LE, rhs - 1)
        case DslRelOp.GT:
            return CirLinear.make(terms, RelOp.GE, rhs + 1)


def _lower_objective(expr: LinearExpr) -> CirObjective:
    terms = tuple((var.key, coef) for var, coef in expr.coeffs)
    return CirObjective(terms, expr.constant)
