"""Implementación de ``ISolver`` sobre Google OR-Tools CP-SAT.

Este es el ÚNICO módulo del sistema que importa ``ortools`` (verificado por
``tests/test_architecture.py``). Mantiene su propio mapeo de handle opaco
(``SolverVar``) a variable nativa de CP-SAT, de modo que ninguna capa superior
ve tipos de OR-Tools. Se importa explícitamente
(``from scheduling_platform.sal.ortools_solver import ORToolsSolver``) para que
``dsl``/``cir``/``pipeline`` no arrastren ``ortools`` al usar ``sal.interface``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ortools.sat.python import cp_model

from .interface import (
    ISolver,
    Literal,
    RelOp,
    SolverConfig,
    SolverInterval,
    SolverStatus,
    SolverVar,
)

_STATUS_MAP = {
    cp_model.OPTIMAL: SolverStatus.OPTIMAL,
    cp_model.FEASIBLE: SolverStatus.FEASIBLE,
    cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
    cp_model.MODEL_INVALID: SolverStatus.MODEL_INVALID,
    cp_model.UNKNOWN: SolverStatus.UNKNOWN,
}


class ORToolsSolver(ISolver):
    """Solver de restricciones respaldado por CP-SAT."""

    def __init__(self) -> None:
        self._model = cp_model.CpModel()
        self._solver = cp_model.CpSolver()
        self._vars: list[cp_model.IntVar] = []
        self._intervals: list[Any] = []
        self._has_objective = False

    def new_bool_var(self, name: str) -> SolverVar:
        handle = len(self._vars)
        self._vars.append(self._model.new_bool_var(name))
        return SolverVar(handle)

    def new_int_var(self, lo: int, hi: int, name: str) -> SolverVar:
        handle = len(self._vars)
        self._vars.append(self._model.new_int_var(lo, hi, name))
        return SolverVar(handle)

    def new_int_var_from_values(self, values: Sequence[int], name: str) -> SolverVar:
        handle = len(self._vars)
        domain = cp_model.Domain.from_values(list(values))
        self._vars.append(self._model.new_int_var_from_domain(domain, name))
        return SolverVar(handle)

    def add_linear(self, terms: Sequence[tuple[SolverVar, int]], op: RelOp, rhs: int) -> None:
        if not terms:
            if not _const_holds(op, rhs):
                self._model.add_bool_or([])  # cláusula vacía: infactible
            return
        expr = sum(coef * self._vars[handle] for handle, coef in terms)
        match op:
            case RelOp.LE:
                self._model.add(expr <= rhs)
            case RelOp.GE:
                self._model.add(expr >= rhs)
            case RelOp.EQ:
                self._model.add(expr == rhs)

    def add_all_different(self, variables: Sequence[SolverVar]) -> None:
        self._model.add_all_different([self._vars[handle] for handle in variables])

    def add_bool_or(self, literals: Sequence[Literal]) -> None:
        self._model.add_bool_or([self._literal(lit) for lit in literals])

    def add_implication(self, antecedent: Literal, consequent: Literal) -> None:
        self._model.add_implication(self._literal(antecedent), self._literal(consequent))

    def new_interval(self, start: SolverVar, size: int, name: str) -> SolverInterval:
        var = self._vars[start]
        interval = self._model.new_fixed_size_interval_var(var, size, name)
        return self._record_interval(interval)

    def new_optional_interval(
        self, start: SolverVar, size: int, presence: Literal, name: str
    ) -> SolverInterval:
        var = self._vars[start]
        interval = self._model.new_optional_interval_var(
            var, size, var + size, self._literal(presence), name
        )
        return self._record_interval(interval)

    def _record_interval(self, interval: Any) -> SolverInterval:
        handle = SolverInterval(len(self._intervals))
        self._intervals.append(interval)
        return handle

    def add_no_overlap(self, intervals: Sequence[SolverInterval]) -> None:
        self._model.add_no_overlap([self._intervals[handle] for handle in intervals])

    def minimize(self, terms: Sequence[tuple[SolverVar, int]], constant: int = 0) -> None:
        expr = sum(coef * self._vars[handle] for handle, coef in terms) + constant
        self._model.minimize(expr)
        self._has_objective = True

    def add_hint(self, var: SolverVar, value: int) -> None:
        self._model.add_hint(self._vars[var], value)

    def solve(self, config: SolverConfig | None = None) -> SolverStatus:
        if config is not None:
            self._apply_config(config)
        status = self._solver.solve(self._model)
        return _STATUS_MAP.get(status, SolverStatus.UNKNOWN)

    def value(self, var: SolverVar) -> int:
        return int(self._solver.value(self._vars[var]))

    def objective_value(self) -> int:
        return int(self._solver.objective_value) if self._has_objective else 0

    def get_stats(self) -> dict[str, int]:
        """Ramas exploradas y conflictos aprendidos en la última búsqueda."""
        try:
            return {
                "num_branches": int(self._solver.num_branches),
                "num_conflicts": int(self._solver.num_conflicts),
            }
        except AttributeError, RuntimeError:  # pragma: no cover - antes de solve
            return {}

    # --- helpers ---

    def _literal(self, literal: Literal) -> cp_model.IntVar:
        var = self._vars[literal.var]
        return var if literal.positive else var.Not()

    def _apply_config(self, config: SolverConfig) -> None:
        params = self._solver.parameters
        if config.max_time_in_seconds is not None:
            params.max_time_in_seconds = config.max_time_in_seconds
        if config.num_search_workers is not None:
            params.num_search_workers = config.num_search_workers
        if config.random_seed is not None:
            params.random_seed = config.random_seed


def _const_holds(op: RelOp, rhs: int) -> bool:
    match op:
        case RelOp.LE:
            return rhs >= 0
        case RelOp.GE:
            return rhs <= 0
        case RelOp.EQ:
            return rhs == 0
