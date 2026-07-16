"""Implementación de ``ISolver`` sobre solvers MILP de OR-Tools (``pywraplp``).

Permite ejecutar el **mismo CIR** en CBC, SCIP, HiGHS (y Gurobi si hay licencia),
cumpliendo la promesa de la SAL: cambiar de solver sin tocar el dominio
(Actividad 7). Junto con ``ortools_solver.py`` es la única otra frontera
autorizada a importar ``ortools`` (verificado por ``tests/test_architecture.py``,
que solo permite el paquete ``sal``).

Los solvers MILP no tienen intervalos ni restricciones globales nativas
(``all_different``, ``no_overlap``): esas operaciones lanzan
:class:`UnsupportedOperation`. Los benchmarks MIP usan por eso la **formulación
booleana** del no-solape (``ResourceNoOverlapPlugin``, ``boolean_starts=True``),
un modelo puramente 0/1 lineal que sí traduce directamente. ``bool_or`` e
``implication`` sí se linealizan (son triviales sobre booleanas).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ortools.linear_solver import pywraplp

from .interface import (
    ISolver,
    Literal,
    RelOp,
    SolverConfig,
    SolverInterval,
    SolverStatus,
    SolverVar,
    UnsupportedOperation,
)

SUPPORTED_BACKENDS = ("CBC", "SCIP", "HiGHS", "GUROBI")


def _status_map(solver: pywraplp.Solver) -> dict[int, SolverStatus]:
    return {
        solver.OPTIMAL: SolverStatus.OPTIMAL,
        solver.FEASIBLE: SolverStatus.FEASIBLE,
        solver.INFEASIBLE: SolverStatus.INFEASIBLE,
    }


class MipSolver(ISolver):
    """``ISolver`` respaldado por un backend MILP de ``pywraplp``."""

    def __init__(self, backend: str = "CBC") -> None:
        solver = pywraplp.Solver.CreateSolver(backend)
        if solver is None:
            raise ValueError(
                f"backend MILP no disponible: {backend} "
                f"(instalados: {', '.join(b for b in SUPPORTED_BACKENDS if b != 'GUROBI')})"
            )
        self.backend = backend
        self._solver = solver
        self._vars: list[Any] = []
        self._objective_terms: list[tuple[int, int]] = []
        self._objective_constant = 0
        self._has_objective = False
        self._hints: list[tuple[int, int]] = []
        self._forced_infeasible = False

    # --- variables ---

    def new_bool_var(self, name: str) -> SolverVar:
        handle = len(self._vars)
        self._vars.append(self._solver.BoolVar(name))
        return SolverVar(handle)

    def new_int_var(self, lo: int, hi: int, name: str) -> SolverVar:
        handle = len(self._vars)
        self._vars.append(self._solver.IntVar(lo, hi, name))
        return SolverVar(handle)

    def new_int_var_from_values(self, values: Sequence[int], name: str) -> SolverVar:
        raise UnsupportedOperation(
            "un backend MILP no admite dominios con huecos; usa la formulación "
            "booleana (boolean_starts=True, ResourceNoOverlapPlugin)"
        )

    # --- restricciones ---

    def add_linear(self, terms: Sequence[tuple[SolverVar, int]], op: RelOp, rhs: int) -> None:
        if not terms:
            if not _const_holds(op, rhs):
                self._forced_infeasible = True
            return
        expr = sum(coef * self._vars[handle] for handle, coef in terms)
        match op:
            case RelOp.LE:
                self._solver.Add(expr <= rhs)
            case RelOp.GE:
                self._solver.Add(expr >= rhs)
            case RelOp.EQ:
                self._solver.Add(expr == rhs)

    def add_all_different(self, variables: Sequence[SolverVar]) -> None:
        raise UnsupportedOperation("all_different no es nativo en MILP")

    def add_bool_or(self, literals: Sequence[Literal]) -> None:
        # Al menos un literal verdadero: sum(lit) >= 1 (linealización trivial).
        expr = sum(self._literal_expr(lit) for lit in literals)
        self._solver.Add(expr >= 1)

    def add_implication(self, antecedent: Literal, consequent: Literal) -> None:
        # a -> b  <=>  b >= a  (sobre 0/1).
        self._solver.Add(self._literal_expr(consequent) >= self._literal_expr(antecedent))

    def new_interval(self, start: SolverVar, size: int, name: str) -> SolverInterval:
        raise UnsupportedOperation("los intervalos no son nativos en MILP")

    def new_optional_interval(
        self, start: SolverVar, size: int, presence: Literal, name: str
    ) -> SolverInterval:
        raise UnsupportedOperation("los intervalos no son nativos en MILP")

    def add_no_overlap(self, intervals: Sequence[SolverInterval]) -> None:
        raise UnsupportedOperation("no_overlap no es nativo en MILP")

    # --- objetivo y búsqueda ---

    def minimize(self, terms: Sequence[tuple[SolverVar, int]], constant: int = 0) -> None:
        objective = self._solver.Objective()
        for handle, coef in terms:
            objective.SetCoefficient(self._vars[handle], float(coef))
        objective.SetOffset(float(constant))
        objective.SetMinimization()
        self._has_objective = True

    def add_hint(self, var: SolverVar, value: int) -> None:
        self._hints.append((int(var), value))

    def solve(self, config: SolverConfig | None = None) -> SolverStatus:
        if self._forced_infeasible:
            return SolverStatus.INFEASIBLE
        if config is not None and config.max_time_in_seconds is not None:
            self._solver.set_time_limit(int(config.max_time_in_seconds * 1000))
        if self._hints:
            handles, values = zip(*self._hints, strict=True)
            self._solver.SetHint([self._vars[h] for h in handles], [float(v) for v in values])
        status = self._solver.Solve()
        return _status_map(self._solver).get(status, SolverStatus.UNKNOWN)

    def value(self, var: SolverVar) -> int:
        solution: float = self._vars[var].solution_value()
        return round(solution)

    def objective_value(self) -> int:
        if not self._has_objective:
            return 0
        value: float = self._solver.Objective().Value()
        return round(value)

    def get_stats(self) -> dict[str, int]:
        # Los backends MILP no exponen ramas/conflictos de forma uniforme; el
        # comparador multi-solver usa tiempo, calidad, RAM y score, no estas.
        return {}

    # --- helpers ---

    def _literal_expr(self, literal: Literal) -> Any:
        var = self._vars[literal.var]
        return var if literal.positive else (1 - var)


def _const_holds(op: RelOp, rhs: int) -> bool:
    match op:
        case RelOp.LE:
            return rhs >= 0
        case RelOp.GE:
            return rhs <= 0
        case RelOp.EQ:
            return rhs == 0
