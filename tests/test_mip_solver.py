"""Multi-solver vía SAL: el mismo CIR en CP-SAT y en los backends MILP (O5).

Se verifica que CBC, SCIP y HiGHS resuelven la formulación booleana con el
**mismo óptimo** que CP-SAT (differential testing), y que las operaciones sin
equivalente MILP (intervalos, all_different, dominios con huecos) fallan de forma
explícita.
"""

from __future__ import annotations

import pytest
from ortools.linear_solver import pywraplp

from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.pipeline import OptimizationPipeline
from scheduling_platform.plugins import SchedulingModelContext, registry_with
from scheduling_platform.plugins.catalog.preferences import PreferEarlySlotsPlugin
from scheduling_platform.plugins.catalog.structural import ResourceNoOverlapPlugin
from scheduling_platform.sal import SolverConfig, SolverStatus
from scheduling_platform.sal.interface import (
    ISolver,
    Literal,
    RelOp,
    UnsupportedOperation,
)
from scheduling_platform.sal.mip_solver import MipSolver
from scheduling_platform.sal.ortools_solver import ORToolsSolver

_CONFIG = SolverConfig(max_time_in_seconds=15.0, random_seed=1)
_MIP_BACKENDS = [b for b in ("CBC", "SCIP", "HiGHS") if pywraplp.Solver.CreateSolver(b) is not None]


def _two_class_problem() -> SchedulingProblem:
    """Un docente, un aula, 2 clases en un día de 3 períodos."""
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([3]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula", frozenset({"room"})),
        ),
        tasks=tuple(
            Task(
                TaskId(i),
                f"Clase {i}",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            )
            for i in range(2)
        ),
    )


def _objective_with(problem: SchedulingProblem, factory: object) -> int:
    context = SchedulingModelContext.build(problem, boolean_starts=True)
    registry = registry_with([ResourceNoOverlapPlugin(), PreferEarlySlotsPlugin(weight=1)])
    model = registry.build_model(context)
    solver: ISolver = factory()  # type: ignore[operator]
    result = OptimizationPipeline().run(problem, model, solver, _CONFIG)
    assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    return solver.objective_value()


def test_backends_disponibles() -> None:
    assert "CBC" in _MIP_BACKENDS
    assert "SCIP" in _MIP_BACKENDS


def test_backend_inexistente_falla_claramente() -> None:
    with pytest.raises(ValueError, match="no disponible"):
        MipSolver("NO_EXISTE")


def test_mismo_optimo_que_cp_sat_en_todos_los_backends() -> None:
    problem = _two_class_problem()
    referencia = _objective_with(problem, ORToolsSolver)
    assert referencia == 1  # 2 clases en {0,1}: offsets 0 + 1
    for backend in _MIP_BACKENDS:
        obtenido = _objective_with(problem, lambda b=backend: MipSolver(b))
        assert obtenido == referencia, f"{backend} dio {obtenido}, esperaba {referencia}"


def test_operaciones_no_soportadas_fallan_explicitamente() -> None:
    mip = MipSolver("CBC")
    v = mip.new_bool_var("v")
    with pytest.raises(UnsupportedOperation):
        mip.new_interval(v, 1, "iv")
    with pytest.raises(UnsupportedOperation):
        mip.new_int_var_from_values([0, 2, 4], "x")
    with pytest.raises(UnsupportedOperation):
        mip.add_all_different([v])


def test_bool_or_e_implicacion_se_linealizan() -> None:
    # x OR y, y ademas x -> y ; minimizando x+y -> ambos a 0 es imposible por el OR,
    # el óptimo es y=1, x=0 (coste 1).
    mip = MipSolver("CBC")
    x = mip.new_bool_var("x")
    y = mip.new_bool_var("y")
    mip.add_bool_or([Literal(x), Literal(y)])
    mip.add_implication(Literal(x), Literal(y))
    mip.minimize([(x, 1), (y, 1)])
    status = mip.solve(_CONFIG)
    assert status is SolverStatus.OPTIMAL
    assert mip.objective_value() == 1
    assert mip.value(y) == 1


def test_modelo_infactible_se_detecta() -> None:
    mip = MipSolver("CBC")
    # suma vacía que no se cumple (0 == 1): infactibilidad estructural.
    mip.add_linear([], RelOp.EQ, 1)
    assert mip.solve(_CONFIG) is SolverStatus.INFEASIBLE
