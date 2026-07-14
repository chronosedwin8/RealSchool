"""Pruebas del FakeSolver y del contrato ISolver (Fase 3)."""

from __future__ import annotations

from scheduling_platform.sal import FakeSolver, SolverConfig, SolverStatus

from .isolver_contract import assert_isolver_contract


def test_fake_solver_cumple_el_contrato_isolver() -> None:
    assert_isolver_contract(FakeSolver)


def test_fake_solver_registra_resultado_predefinido() -> None:
    solver = FakeSolver()
    x = solver.new_int_var(0, 10, "x")
    solver.set_result(SolverStatus.OPTIMAL, {x: 7}, objective_value=42)
    assert solver.solve() is SolverStatus.OPTIMAL
    assert solver.value(x) == 7
    assert solver.objective_value() == 42


def test_fake_solver_recuerda_configuracion() -> None:
    solver = FakeSolver()
    config = SolverConfig(max_time_in_seconds=5.0, random_seed=3)
    solver.solve(config)
    assert solver.configs_seen == [config]


def test_handles_de_variables_son_distintos() -> None:
    solver = FakeSolver()
    handles = [solver.new_bool_var(f"b{i}") for i in range(4)]
    assert len(set(handles)) == 4
