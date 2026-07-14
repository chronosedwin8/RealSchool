"""Evaluador de referencia del CIR.

Comprueba si una asignación concreta satisface todas las restricciones de un
:class:`CirModel`, de forma independiente del solver. Es la base de las pruebas
de preservación semántica (Fase 4) y una herramienta para el Validation Engine
(Fase 9). No optimiza: solo evalúa lógica pura.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import pairwise

from ..sal.interface import RelOp
from .nodes import (
    CirAllDifferent,
    CirBoolOr,
    CirConstraint,
    CirImplication,
    CirLinear,
    CirLiteral,
    CirModel,
    CirNoOverlap,
)


def satisfies(model: CirModel, assignment: Mapping[str, int]) -> bool:
    """``True`` si ``assignment`` cumple todas las restricciones del modelo."""
    return all(constraint_holds(c, assignment) for c in model.constraints)


def constraint_holds(constraint: CirConstraint, assignment: Mapping[str, int]) -> bool:
    if isinstance(constraint, CirLinear):
        total = sum(coef * assignment[key] for key, coef in constraint.terms)
        return _compare(total, constraint.op, constraint.rhs)
    if isinstance(constraint, CirAllDifferent):
        values = [assignment[key] for key in constraint.keys]
        return len(set(values)) == len(values)
    if isinstance(constraint, CirBoolOr):
        return any(_literal_true(lit, assignment) for lit in constraint.literals)
    if isinstance(constraint, CirImplication):
        return (not _literal_true(constraint.antecedent, assignment)) or _literal_true(
            constraint.consequent, assignment
        )
    if isinstance(constraint, CirNoOverlap):
        presentes = [
            (assignment[spec.start_key], assignment[spec.start_key] + spec.size)
            for spec in constraint.intervals
            if spec.presence is None or _literal_true(spec.presence, assignment)
        ]
        presentes.sort()
        return all(
            actual_end <= next_start for (_, actual_end), (next_start, _) in pairwise(presentes)
        )
    raise TypeError(f"nodo CIR no evaluable: {constraint!r}")  # pragma: no cover


def _compare(lhs: int, op: RelOp, rhs: int) -> bool:
    match op:
        case RelOp.LE:
            return lhs <= rhs
        case RelOp.GE:
            return lhs >= rhs
        case RelOp.EQ:
            return lhs == rhs


def _literal_true(literal: CirLiteral, assignment: Mapping[str, int]) -> bool:
    value = assignment[literal.key]
    return value == 1 if literal.positive else value == 0
