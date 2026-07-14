"""Solver Compiler: CIR -> ``ISolver``.

Última etapa del pipeline de compilación (Prompt3 §2.3). Recibe el CIR ya
optimizado por los pases y lo instancia en un solver concreto a través de la
SAL. No conoce ningún solver en particular: habla solo con ``ISolver``.
"""

from __future__ import annotations

from ..dsl.domain import BoolDomain, EnumDomain, IntDomain
from ..sal.interface import ISolver, Literal, SolverInterval, SolverVar
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
)


class CirToSolverCompiler:
    """Baja un :class:`CirModel` a un ``ISolver`` concreto."""

    def compile(self, model: CirModel, solver: ISolver) -> dict[str, SolverVar]:
        var_map: dict[str, SolverVar] = {}
        for key, domain in model.variables:
            if isinstance(domain, BoolDomain):
                var_map[key] = solver.new_bool_var(key)
            elif isinstance(domain, IntDomain):
                var_map[key] = solver.new_int_var(domain.lo, domain.hi, key)
            elif isinstance(domain, EnumDomain):
                var_map[key] = solver.new_int_var_from_values(domain.values, key)
            else:  # pragma: no cover - dominio desconocido
                raise CirError(f"dominio no soportado: {domain!r}")

        for constraint in model.constraints:
            self._lower(constraint, solver, var_map)

        if model.objective is not None:
            terms = [(var_map[key], coef) for key, coef in model.objective.terms]
            solver.minimize(terms, model.objective.constant)
        return var_map

    def _lower(
        self, constraint: CirConstraint, solver: ISolver, var_map: dict[str, SolverVar]
    ) -> None:
        if isinstance(constraint, CirLinear):
            terms = [(var_map[key], coef) for key, coef in constraint.terms]
            solver.add_linear(terms, constraint.op, constraint.rhs)
        elif isinstance(constraint, CirAllDifferent):
            solver.add_all_different([var_map[key] for key in constraint.keys])
        elif isinstance(constraint, CirBoolOr):
            solver.add_bool_or([self._literal(lit, var_map) for lit in constraint.literals])
        elif isinstance(constraint, CirImplication):
            solver.add_implication(
                self._literal(constraint.antecedent, var_map),
                self._literal(constraint.consequent, var_map),
            )
        elif isinstance(constraint, CirNoOverlap):
            handles = [
                self._interval(spec, index, solver, var_map)
                for index, spec in enumerate(constraint.intervals)
            ]
            solver.add_no_overlap(handles)
        else:  # pragma: no cover - nodo desconocido
            raise CirError(f"nodo CIR no soportado: {constraint!r}")

    @staticmethod
    def _literal(literal: CirLiteral, var_map: dict[str, SolverVar]) -> Literal:
        return Literal(var_map[literal.key], literal.positive)

    def _interval(
        self,
        spec: CirIntervalSpec,
        index: int,
        solver: ISolver,
        var_map: dict[str, SolverVar],
    ) -> SolverInterval:
        start = var_map[spec.start_key]
        name = f"iv#{spec.start_key}#{index}"
        if spec.presence is None:
            return solver.new_interval(start, spec.size, name)
        return solver.new_optional_interval(
            start, spec.size, self._literal(spec.presence, var_map), name
        )
