"""Pruebas del orquestador del pipeline y del Conflict Explanation Engine (Fase 5)."""

from __future__ import annotations

from scheduling_platform.cir.exceptions import StructuralContradictionError
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.dsl import DslModel, IntDomain, LinearConstraint, Var
from scheduling_platform.pipeline import (
    ConflictExplanationEngine,
    OptimizationPipeline,
    StructuralIssue,
)
from scheduling_platform.sal import FakeSolver, SolverConfig, SolverStatus


def _feasible_problem() -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher#0"})),
            Resource(ResourceId(1), "Aula", frozenset({"room"})),
            Resource(ResourceId(2), "Aula 2", frozenset({"room"})),
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


def _infeasible_problem() -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(Resource(ResourceId(0), "Aula", frozenset({"room"})),),
        tasks=(Task(TaskId(0), "Química", 1, (ResourceRequirement("lab"),)),),
    )


# --- Conflict Explanation Engine ---


def test_explica_contradiccion_del_cir() -> None:
    error = StructuralContradictionError(("a == 9 está fuera de su dominio",))
    report = ConflictExplanationEngine().explain_contradiction(error)
    assert report.feasible is False
    assert "fuera de su dominio" in report.render()


def test_report_factible_se_renderiza() -> None:
    report = ConflictExplanationEngine().explain_structural([])
    assert report.feasible is True
    assert "Sin conflictos" in report.render()


def test_report_infactible_lista_issues() -> None:
    report = ConflictExplanationEngine().explain_structural(
        [StructuralIssue("k", "mensaje accionable")]
    )
    assert "mensaje accionable" in report.render()


# --- Pipeline end-to-end con FakeSolver ---


def test_pipeline_se_detiene_ante_infactibilidad_estructural() -> None:
    solver = FakeSolver()
    dsl = DslModel(constraints=())
    result = OptimizationPipeline().run(_infeasible_problem(), dsl, solver)
    assert result.stopped_before_solver
    assert result.report.feasible is False
    # el solver nunca fue invocado
    assert solver.configs_seen == []


def test_pipeline_resuelve_problema_factible() -> None:
    solver = FakeSolver()
    x = Var("x", IntDomain(0, 5))
    dsl = DslModel(constraints=(LinearConstraint(x <= 3),))
    solver.set_result(SolverStatus.OPTIMAL, {}, objective_value=0)
    result = OptimizationPipeline().run(
        _feasible_problem(), dsl, solver, SolverConfig(random_seed=1)
    )
    assert result.status is SolverStatus.OPTIMAL
    assert result.var_map is not None and "x" in result.var_map
    assert solver.configs_seen == [SolverConfig(random_seed=1)]


def test_pipeline_detecta_contradiccion_del_cir_sin_invocar_solver() -> None:
    solver = FakeSolver()
    x = Var("x", IntDomain(0, 5))
    # x == 9 con dominio [0,5]: contradicción estructural detectada en los pases
    dsl = DslModel(constraints=(LinearConstraint(x.eq(9)),))
    result = OptimizationPipeline().run(_feasible_problem(), dsl, solver)
    assert result.stopped_before_solver
    assert result.report.feasible is False
    assert solver.configs_seen == []


def test_pipeline_analyze_devuelve_report() -> None:
    report = OptimizationPipeline().analyze(_feasible_problem())
    assert report.feasible is True
