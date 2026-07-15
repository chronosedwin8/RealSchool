"""Arnés de contrato reutilizable para implementaciones de ``ISolver``.

Verifica las propiedades estructurales que toda implementación debe cumplir.
La Fase 7 lo reutilizará para ``ORToolsSolver`` (que además comprobará la
resolución real). Aquí lo consume el ``FakeSolver``.
"""

from __future__ import annotations

from collections.abc import Callable

from scheduling_platform.sal import ISolver, Literal, RelOp, SolverConfig

SolverFactory = Callable[[], ISolver]


def assert_isolver_contract(make_solver: SolverFactory) -> None:
    """Comprueba el contrato mínimo de ``ISolver`` sobre ``make_solver()``."""
    solver = make_solver()

    # 1. Las variables reciben handles distintos.
    a = solver.new_bool_var("a")
    b = solver.new_bool_var("b")
    x = solver.new_int_var(0, 10, "x")
    assert len({a, b, x}) == 3

    # 2. Los métodos de publicación aceptan las estructuras esperadas.
    solver.add_linear([(x, 1)], RelOp.LE, 10)
    solver.add_all_different([a, b])
    solver.add_bool_or([Literal(a), Literal(b, positive=False)])
    solver.add_implication(Literal(a), Literal(b))
    solver.minimize([(x, 1)], constant=0)
    solver.add_hint(x, 0)  # warm start: sugerencia, no restricción

    # 3. Intervalos: fijos, opcionales y no-solape.
    y = solver.new_int_var(0, 10, "y")
    fijo = solver.new_interval(x, 2, "iv_x")
    opcional = solver.new_optional_interval(y, 2, Literal(a), "iv_y")
    assert fijo != opcional
    solver.add_no_overlap([fijo, opcional])

    # 4. solve acepta configuración y None, y devuelve un SolverStatus.
    from scheduling_platform.sal import SolverStatus

    status = solver.solve(SolverConfig(random_seed=1, num_search_workers=1))
    assert isinstance(status, SolverStatus)
    assert isinstance(solver.solve(None), SolverStatus)
