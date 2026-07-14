"""Compilador DSL -> ``ISolver`` (Solver Compiler, forma inicial).

Crea una variable de solver por cada :class:`Var` del modelo y baja cada
restricción a llamadas de ``ISolver``. En la Fase 3 el compilador consume el
DSL directamente; en la Fase 4 se interpondrá el CIR (DSL -> CIR -> pases ->
Solver Compiler) sin alterar ni el DSL ni la SAL: este módulo pasará a consumir
el CIR optimizado en lugar del DSL.
"""

from __future__ import annotations

from ..sal.interface import ISolver, Literal, RelOp, SolverVar
from .domain import BoolDomain, IntDomain
from .exceptions import DslError, UnsupportedConstraintError
from .expressions import DslRelOp, LinearExpr, Relation, Var
from .logic import (
    AllDifferentConstraint,
    BoolOrConstraint,
    DslConstraint,
    DslLiteral,
    ImplicationConstraint,
    LinearConstraint,
)
from .model import DslModel


class DslToSolverCompiler:
    """Baja un :class:`DslModel` a un ``ISolver`` concreto."""

    def compile(self, model: DslModel, solver: ISolver) -> dict[Var, SolverVar]:
        var_map = self._create_variables(model, solver)
        for constraint in model.constraints:
            self._lower_constraint(constraint, solver, var_map)
        if model.objective is not None:
            terms, constant = self._linear_terms(model.objective.expr, var_map)
            solver.minimize(terms, constant)
        return var_map

    def _create_variables(self, model: DslModel, solver: ISolver) -> dict[Var, SolverVar]:
        by_key: dict[str, Var] = {}
        var_map: dict[Var, SolverVar] = {}
        for var in sorted(model.variables(), key=lambda v: v.key):
            existing = by_key.get(var.key)
            if existing is not None and existing.domain != var.domain:
                raise DslError(f"la key de variable '{var.key}' se usa con dominios distintos")
            by_key[var.key] = var
            if isinstance(var.domain, BoolDomain):
                var_map[var] = solver.new_bool_var(var.key)
            elif isinstance(var.domain, IntDomain):
                var_map[var] = solver.new_int_var(var.domain.lo, var.domain.hi, var.key)
            else:  # pragma: no cover - dominio desconocido
                raise DslError(f"dominio no soportado: {var.domain!r}")
        return var_map

    def _lower_constraint(
        self, constraint: DslConstraint, solver: ISolver, var_map: dict[Var, SolverVar]
    ) -> None:
        if isinstance(constraint, LinearConstraint):
            terms, op, rhs = self._relation_to_solver(constraint.relation, var_map)
            solver.add_linear(terms, op, rhs)
        elif isinstance(constraint, AllDifferentConstraint):
            solver.add_all_different([var_map[v] for v in constraint.variables_])
        elif isinstance(constraint, BoolOrConstraint):
            solver.add_bool_or([self._to_sal_literal(lit, var_map) for lit in constraint.literals])
        elif isinstance(constraint, ImplicationConstraint):
            solver.add_implication(
                self._to_sal_literal(constraint.antecedent, var_map),
                self._to_sal_literal(constraint.consequent, var_map),
            )
        else:  # pragma: no cover - forma futura (Fase 4)
            raise UnsupportedConstraintError(f"forma de restricción no soportada: {constraint!r}")

    @staticmethod
    def _to_sal_literal(literal: DslLiteral, var_map: dict[Var, SolverVar]) -> Literal:
        return Literal(var_map[literal.var], literal.positive)

    @staticmethod
    def _linear_terms(
        expr: LinearExpr, var_map: dict[Var, SolverVar]
    ) -> tuple[list[tuple[SolverVar, int]], int]:
        terms = [(var_map[var], coef) for var, coef in expr.coeffs]
        return terms, expr.constant

    def _relation_to_solver(
        self, relation: Relation, var_map: dict[Var, SolverVar]
    ) -> tuple[list[tuple[SolverVar, int]], RelOp, int]:
        # relation.expr OP 0, con expr = sum(coef*var) + k  ->  sum(coef*var) OP -k
        terms, constant = self._linear_terms(relation.expr, var_map)
        rhs = -constant
        match relation.op:
            case DslRelOp.LE:
                return terms, RelOp.LE, rhs
            case DslRelOp.GE:
                return terms, RelOp.GE, rhs
            case DslRelOp.EQ:
                return terms, RelOp.EQ, rhs
            case DslRelOp.LT:
                # expr < 0  <=>  sum <= -k - 1 (variables enteras)
                return terms, RelOp.LE, rhs - 1
            case DslRelOp.GT:
                # expr > 0  <=>  sum >= -k + 1
                return terms, RelOp.GE, rhs + 1
