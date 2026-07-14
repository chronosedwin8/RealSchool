"""Orquestador del Optimization Pipeline (Prompt3 §3).

Encadena las etapas pre-solver y de compilación:

1. **Análisis de factibilidad** (Constraint Graph Builder) sobre el problema
   canónico. Si es infactible, se explica y se detiene (no se invoca al solver).
2. **Compilación de restricciones**: ``lower(DSL) -> CIR -> PassManager``. Si un
   pase detecta una contradicción estructural, se explica y se detiene.
3. **Solver Compiler**: instancia el CIR en el ``ISolver`` inyectado y resuelve.

La extracción de la solución, las métricas y la reoptimización se añaden en
fases posteriores (7/9/10). El solver se inyecta (DI): en pruebas se usa el
``FakeSolver``; en producción, ``ORToolsSolver`` (Fase 7).
"""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Resultado de una corrida del pipeline."""

    report: ConflictReport
    status: SolverStatus | None = None
    var_map: Mapping[str, SolverVar] | None = None

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
        report = self.analyze(problem)
        if not report.feasible:
            return PipelineResult(report=report)

        try:
            cir = self.pass_manager.run(lower(dsl_model))
        except StructuralContradictionError as error:
            return PipelineResult(report=self.explainer.explain_contradiction(error))

        var_map = self.compiler.compile(cir, solver)
        status = solver.solve(config)
        return PipelineResult(report=report, status=status, var_map=var_map)
