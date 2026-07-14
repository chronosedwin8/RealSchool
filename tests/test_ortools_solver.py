"""Pruebas del ORToolsSolver y del modelo CP-SAT end-to-end (Fase 7).

Incluye las pruebas de rigor del modelo matemático: contrato de ``ISolver``
sobre el solver real, **oráculos** con óptimo calculado a mano, **determinismo**
con semilla fija y **metamórficas** (permutar la entrada no cambia el óptimo).
"""

from __future__ import annotations

from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.dsl import DslModel, Objective
from scheduling_platform.dsl.expressions import LinearExpr
from scheduling_platform.pipeline import OptimizationPipeline, PipelineResult
from scheduling_platform.plugins import SchedulingModelContext
from scheduling_platform.plugins.catalog.structural import ResourceNoOverlapPlugin
from scheduling_platform.sal import RelOp, SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

from .isolver_contract import assert_isolver_contract

# --- Contrato y comportamiento básico del solver real ---


def test_ortools_cumple_contrato_isolver() -> None:
    assert_isolver_contract(ORToolsSolver)


def test_ortools_optimiza_caso_trivial() -> None:
    solver = ORToolsSolver()
    a = solver.new_bool_var("a")
    b = solver.new_bool_var("b")
    solver.add_linear([(a, 1), (b, 1)], RelOp.EQ, 1)  # a + b == 1
    solver.minimize([(a, 1)])  # minimizar a -> a=0, b=1
    status = solver.solve(SolverConfig(random_seed=1, num_search_workers=1))
    assert status is SolverStatus.OPTIMAL
    assert solver.value(a) == 0
    assert solver.value(b) == 1
    assert solver.objective_value() == 0


def test_ortools_detecta_infactible() -> None:
    solver = ORToolsSolver()
    x = solver.new_int_var(0, 5, "x")
    solver.add_linear([(x, 1)], RelOp.GE, 10)  # x >= 10 con x <= 5
    assert solver.solve() is SolverStatus.INFEASIBLE


def test_ortools_constante_infactible_y_trivial() -> None:
    infactible = ORToolsSolver()
    infactible.add_linear([], RelOp.EQ, 1)  # 0 == 1 -> infactible
    assert infactible.solve() is SolverStatus.INFEASIBLE

    trivial = ORToolsSolver()
    x = trivial.new_int_var(0, 5, "x")
    trivial.add_linear([], RelOp.LE, 5)  # 0 <= 5 -> no aporta nada
    trivial.add_linear([(x, 1)], RelOp.LE, 3)
    assert trivial.solve() in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)


def test_ortools_sin_objetivo_devuelve_cero() -> None:
    solver = ORToolsSolver()
    x = solver.new_int_var(0, 5, "x")
    solver.add_linear([(x, 1)], RelOp.LE, 3)
    assert solver.solve() in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert solver.objective_value() == 0


def test_ortools_respeta_limite_de_tiempo() -> None:
    solver = ORToolsSolver()
    x = solver.new_int_var(0, 5, "x")
    solver.add_linear([(x, 1)], RelOp.LE, 3)
    status = solver.solve(SolverConfig(max_time_in_seconds=2.0, num_search_workers=1))
    assert status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)


# --- Modelo end-to-end: oráculo con óptimo conocido ---


def _packing_problem() -> SchedulingProblem:
    """3 clases de 1 período, 1 docente y 1 aula, en 3 slots.

    El no-solape obliga a ocupar los 3 slots distintos; minimizar la suma de
    inicios fuerza {0,1,2}, con óptimo conocido = 0+1+2 = 3.
    """
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([3]),
        resources=(
            Resource(ResourceId(0), "Prof. Juan", frozenset({"teacher#0"})),
            Resource(ResourceId(1), "Aula", frozenset({"room"})),
        ),
        tasks=tuple(
            Task(
                TaskId(i),
                f"Clase {i}",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            )
            for i in range(3)
        ),
    )


def _build_model(context: SchedulingModelContext) -> DslModel:
    constraints = list(context.structural_constraints())
    constraints.extend(ResourceNoOverlapPlugin().contribute(context).constraints)
    objective_expr = LinearExpr.of(0)
    for task in context.problem.tasks:
        tid = int(task.id)
        for slot in context.valid_starts(tid):
            objective_expr = objective_expr + slot * context.start_var(tid, slot)
    return DslModel(tuple(constraints), Objective(objective_expr))


def _chosen_starts(
    context: SchedulingModelContext, result: PipelineResult, solver: ORToolsSolver
) -> dict[int, int]:
    var_map = result.var_map
    assert var_map is not None
    chosen: dict[int, int] = {}
    for task in context.problem.tasks:
        tid = int(task.id)
        for slot in context.valid_starts(tid):
            key = context.start_var(tid, slot).key
            if key in var_map and solver.value(var_map[key]) == 1:
                chosen[tid] = slot
    return chosen


def test_oraculo_packing_optimo_conocido() -> None:
    problem = _packing_problem()
    context = SchedulingModelContext.build(problem)
    model = _build_model(context)
    solver = ORToolsSolver()
    result = OptimizationPipeline().run(problem, model, solver, SolverConfig(random_seed=1))
    assert result.status is SolverStatus.OPTIMAL
    assert solver.objective_value() == 3
    chosen = _chosen_starts(context, result, solver)
    assert sorted(chosen.values()) == [0, 1, 2]  # no-solape: slots distintos


def test_determinismo_con_semilla_fija() -> None:
    problem = _packing_problem()

    def run_once() -> dict[int, int]:
        context = SchedulingModelContext.build(problem)
        model = _build_model(context)
        solver = ORToolsSolver()
        result = OptimizationPipeline().run(
            problem, model, solver, SolverConfig(random_seed=7, num_search_workers=1)
        )
        assert result.status is SolverStatus.OPTIMAL
        return _chosen_starts(context, result, solver)

    assert run_once() == run_once()


def test_metamorfico_permutar_entrada_no_cambia_optimo() -> None:
    base = _packing_problem()
    # misma instancia con las tareas en orden inverso
    permuted = SchedulingProblem(
        grid=base.grid,
        resources=tuple(reversed(base.resources)),
        tasks=tuple(reversed(base.tasks)),
    )

    def optimum(problem: SchedulingProblem) -> int:
        context = SchedulingModelContext.build(problem)
        model = _build_model(context)
        solver = ORToolsSolver()
        result = OptimizationPipeline().run(problem, model, solver, SolverConfig(random_seed=1))
        assert result.status is SolverStatus.OPTIMAL
        return solver.objective_value()

    assert optimum(base) == optimum(permuted) == 3


def test_no_solape_ignora_recursos_no_unarios_y_sin_choque() -> None:
    # Recurso de capacidad 2 (no unario) y otro con una sola tarea candidata:
    # el plugin no debe generar restricciones de no-solape.
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([3]),
        resources=(
            Resource(ResourceId(0), "Auditorio", frozenset({"room"}), capacity=2),
            Resource(ResourceId(1), "Prof", frozenset({"teacher#0"})),
        ),
        tasks=(
            Task(
                TaskId(0),
                "Mate",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            ),
        ),
    )
    context = SchedulingModelContext.build(problem)
    contribution = ResourceNoOverlapPlugin().contribute(context)
    assert contribution.constraints == ()


def test_no_solape_garantiza_slots_distintos_para_docente() -> None:
    problem = _packing_problem()
    context = SchedulingModelContext.build(problem)
    model = _build_model(context)
    solver = ORToolsSolver()
    result = OptimizationPipeline().run(problem, model, solver, SolverConfig(random_seed=1))
    chosen = _chosen_starts(context, result, solver)
    # las 3 clases del mismo docente ocupan slots distintos
    assert len(set(chosen.values())) == 3
