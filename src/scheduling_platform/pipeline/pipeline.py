"""Orquestador del Optimization Pipeline (Prompt3 §3).

Encadena las etapas pre-solver y de compilación:

1. **Análisis de factibilidad** (Constraint Graph Builder) sobre el problema
   canónico. Si es infactible, se explica y se detiene (no se invoca al solver).
2. **Compilación de restricciones**: ``lower(DSL) -> CIR -> PassManager``. Si un
   pase detecta una contradicción estructural, se explica y se detiene.
3. **Solver Compiler**: instancia el CIR en el ``ISolver`` inyectado y resuelve.

Cada etapa se cronometra y se reporta en :class:`Telemetry`. El solver se
inyecta (DI): en pruebas se usa el ``FakeSolver``; en producción,
``ORToolsSolver``. La extracción de la solución y su validación viven en la capa
``engine`` (Fase 9).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..cir.compiler import CirToSolverCompiler
from ..cir.exceptions import StructuralContradictionError
from ..cir.lowering import lower
from ..cir.passes import PassManager
from ..core.problem import SchedulingProblem
from ..dsl.model import DslModel
from ..sal.interface import ISolver, SolverConfig, SolverStatus, SolverVar
from .conflict_explanation import ConflictExplanationEngine
from .graph_builder import ConstraintGraphBuilder
from .issues import ConflictReport
from .telemetry import Telemetry


def _ms_since(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Resultado de una corrida del pipeline."""

    report: ConflictReport
    status: SolverStatus | None = None
    var_map: Mapping[str, SolverVar] | None = None
    telemetry: Telemetry | None = None

    @property
    def stopped_before_solver(self) -> bool:
        """``True`` si se detuvo por infactibilidad antes de resolver."""
        return self.status is None


@dataclass(frozen=True, slots=True)
class OptimizationPipeline:
    """Orquesta el análisis, la compilación y la resolución."""

    graph_builder: ConstraintGraphBuilder = field(default_factory=ConstraintGraphBuilder)
    explainer: ConflictExplanationEngine = field(default_factory=ConflictExplanationEngine)
    pass_manager: PassManager = field(default_factory=PassManager.default)
    compiler: CirToSolverCompiler = field(default_factory=CirToSolverCompiler)

    def analyze(self, problem: SchedulingProblem) -> ConflictReport:
        """Solo el análisis de factibilidad pre-solver."""
        issues = self.graph_builder.analyze(problem)
        return self.explainer.explain_structural(issues)

    def run(
        self,
        problem: SchedulingProblem,
        dsl_model: DslModel,
        solver: ISolver,
        config: SolverConfig | None = None,
    ) -> PipelineResult:
        total_start = time.perf_counter()

        stage = time.perf_counter()
        report = self.analyze(problem)
        t_analyze = _ms_since(stage)
        if not report.feasible:
            return PipelineResult(
                report=report,
                telemetry=Telemetry(t_analyze_ms=t_analyze, t_total_ms=_ms_since(total_start)),
            )

        stage = time.perf_counter()
        cir = lower(dsl_model)
        t_lower = _ms_since(stage)
        constraints_before = len(cir.constraints)

        stage = time.perf_counter()
        try:
            cir = self.pass_manager.run(cir)
        except StructuralContradictionError as error:
            return PipelineResult(
                report=self.explainer.explain_contradiction(error),
                telemetry=Telemetry(
                    t_analyze_ms=t_analyze,
                    t_lower_ms=t_lower,
                    t_passes_ms=_ms_since(stage),
                    t_total_ms=_ms_since(total_start),
                    num_constraints_before_passes=constraints_before,
                ),
            )
        t_passes = _ms_since(stage)

        stage = time.perf_counter()
        var_map = self.compiler.compile(cir, solver)
        t_compile = _ms_since(stage)

        stage = time.perf_counter()
        status = solver.solve(config)
        t_solve = _ms_since(stage)

        telemetry = Telemetry(
            t_analyze_ms=t_analyze,
            t_lower_ms=t_lower,
            t_passes_ms=t_passes,
            t_compile_ms=t_compile,
            t_solve_ms=t_solve,
            t_total_ms=_ms_since(total_start),
            num_variables=len(cir.variables),
            num_constraints=len(cir.constraints),
            num_constraints_before_passes=constraints_before,
        )
        return PipelineResult(report=report, status=status, var_map=var_map, telemetry=telemetry)
