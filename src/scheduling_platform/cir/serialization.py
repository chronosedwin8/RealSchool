"""Serialización textual determinista del CIR (para snapshot tests y depuración)."""

from __future__ import annotations

from ..dsl.domain import BoolDomain, Domain, IntDomain
from .nodes import (
    CirAllDifferent,
    CirBoolOr,
    CirConstraint,
    CirImplication,
    CirLinear,
    CirLiteral,
    CirModel,
)


def cir_to_text(model: CirModel) -> str:
    """Representación textual estable de un modelo CIR."""
    lines: list[str] = ["VARS"]
    for key, domain in model.variables:
        lines.append(f"  {key}: {_domain_text(domain)}")
    lines.append("CONSTRAINTS")
    for constraint in model.constraints:
        lines.append(f"  {_constraint_text(constraint)}")
    if model.objective is not None:
        lines.append("OBJECTIVE")
        lines.append(
            f"  minimize {_terms_text(model.objective.terms)} + {model.objective.constant}"
        )
    return "\n".join(lines)


def _domain_text(domain: Domain) -> str:
    if isinstance(domain, BoolDomain):
        return "bool"
    if isinstance(domain, IntDomain):
        return f"int[{domain.lo},{domain.hi}]"
    return repr(domain)  # pragma: no cover


def _terms_text(terms: tuple[tuple[str, int], ...]) -> str:
    if not terms:
        return "0"
    return " + ".join(f"{coef}*{key}" for key, coef in terms)


def _literal_text(literal: CirLiteral) -> str:
    return literal.key if literal.positive else f"~{literal.key}"


def _constraint_text(constraint: CirConstraint) -> str:
    if isinstance(constraint, CirLinear):
        return f"LINEAR {_terms_text(constraint.terms)} {constraint.op.value} {constraint.rhs}"
    if isinstance(constraint, CirAllDifferent):
        return f"ALLDIFF {', '.join(constraint.keys)}"
    if isinstance(constraint, CirBoolOr):
        return f"BOOLOR {', '.join(_literal_text(lit) for lit in constraint.literals)}"
    if isinstance(constraint, CirImplication):
        return (
            f"IMPL {_literal_text(constraint.antecedent)} -> {_literal_text(constraint.consequent)}"
        )
    raise TypeError(f"nodo CIR no serializable: {constraint!r}")  # pragma: no cover
