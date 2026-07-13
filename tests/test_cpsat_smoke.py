"""Smoke tests de CP-SAT sobre Python 3.14 / Windows.

Verifican que el wheel cp314 de OR-Tools resuelve correctamente antes de
construir nada encima: optimización trivial, intervalos con NoOverlap y
determinismo con semilla fija.
"""

from ortools.sat.python import cp_model


def test_optimizacion_trivial_con_optimo_conocido() -> None:
    model = cp_model.CpModel()
    x = model.new_bool_var("x")
    y = model.new_bool_var("y")
    model.add(x + y == 1)
    model.maximize(2 * x + y)

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    assert status == cp_model.OPTIMAL
    assert solver.value(x) == 1
    assert solver.value(y) == 0
    assert solver.objective_value == 2


def test_no_overlap_empaqueta_intervalos_sin_huecos() -> None:
    # Tres tareas de duración 2 en un recurso exclusivo con horizonte 6:
    # la única distribución factible es [0, 2, 4].
    model = cp_model.CpModel()
    horizonte = 6
    inicios = [model.new_int_var(0, horizonte - 2, f"inicio_{i}") for i in range(3)]
    intervalos = [
        model.new_fixed_size_interval_var(inicios[i], 2, f"intervalo_{i}") for i in range(3)
    ]
    model.add_no_overlap(intervalos)

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert sorted(solver.value(s) for s in inicios) == [0, 2, 4]


def test_determinismo_con_semilla_fija() -> None:
    def resolver() -> list[int]:
        model = cp_model.CpModel()
        variables = [model.new_int_var(0, 9, f"v{i}") for i in range(5)]
        model.add_all_different(variables)
        model.maximize(sum((i + 1) * v for i, v in enumerate(variables)))
        solver = cp_model.CpSolver()
        solver.parameters.random_seed = 7
        solver.parameters.num_search_workers = 1
        assert solver.solve(model) == cp_model.OPTIMAL
        return [solver.value(v) for v in variables]

    assert resolver() == resolver()
