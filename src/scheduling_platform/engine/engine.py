"""API pública del motor de calendarización.

Punto de entrada único: se le da un problema canónico y devuelve un resultado
completo (estado, horario, informe de penalizaciones, validación independiente y
telemetría). El solver se inyecta como *factory* (DI), de modo que el motor no
conoce OR-Tools:

    engine = SchedulingEngine(registry, ORToolsSolver)
    result = engine.solve(problem, SolverConfig(random_seed=1))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..core.problem import SchedulingProblem
from ..core.solution import Solution
from ..pipeline.issues import ConflictReport
from ..pipeline.pipeline import OptimizationPipeline
from ..pipeline.telemetry import Telemetry
from ..plugins.context import SchedulingModelContext
from ..plugins.registry import PluginRegistry
from ..sal.interface import ISolver, SolverConfig, SolverStatus
from .solution_builder import SolutionBuilder
from .validation import ValidationEngine, ValidationReport

SolverFactory = Callable[[], ISolver]

_SOLVED = (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)


@dataclass(frozen=True, slots=True)
class EngineResult:
    """Resultado completo de una corrida del motor."""

    status: SolverStatus | None
    report: ConflictReport
    solution: Solution | None = None
    validation: ValidationReport | None = None
    telemetry: Telemetry | None = None

    @property
    def solved(self) -> bool:
        """``True`` si se obtuvo un horario que además superó la validación."""
        return self.solution is not None and self.validation is not None and self.validation.valid

    def render(self) -> str:
        """Resumen legible del resultado."""
        if self.solution is None:
            return self.report.render()
        lines = [f"Horario generado ({self.status.value if self.status else '?'})."]
        lines.append(f"Score (objetivo minimizado): {self.solution.objective_value}")
        if self.solution.penalties:
            lines.append("Informe de penalizaciones:")
            lines.extend(
                f"  - {penalty.source}: {penalty.amount}" for penalty in self.solution.penalties
            )
        else:
            lines.append("Sin penalizaciones: se cumplen todas las preferencias.")
        if self.validation is not None:
            lines.append(self.validation.render())
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class SchedulingEngine:
    """Fachada del motor: plugins + pipeline + extracción + validación."""

    registry: PluginRegistry
    solver_factory: SolverFactory
    pipeline: OptimizationPipeline = field(default_factory=OptimizationPipeline)
    builder: SolutionBuilder = field(default_factory=SolutionBuilder)
    validator: ValidationEngine = field(default_factory=ValidationEngine)
    boolean_starts: bool = True
    """Codificación booleana de los inicios.

    Necesaria para las reglas que razonan período a período (preferencias,
    almuerzo, carga diaria). Si ninguna regla activa la usa, ponerlo a ``False``
    reduce drásticamente el modelo en instituciones grandes.
    """

    def solve(self, problem: SchedulingProblem, config: SolverConfig | None = None) -> EngineResult:
        context = SchedulingModelContext.build(problem, boolean_starts=self.boolean_starts)
        model, penalties = self.registry.build(context)  # una sola consulta a los plugins

        solver = self.solver_factory()
        result = self.pipeline.run(problem, model, solver, config)

        if result.status not in _SOLVED or result.var_map is None:
            return EngineResult(
                status=result.status,
                report=result.report,
                telemetry=result.telemetry,
            )

        solution = self.builder.build(context, result.var_map, solver, penalties)
        validation = self.validator.validate(problem, solution)
        return EngineResult(
            status=result.status,
            report=result.report,
            solution=solution,
            validation=validation,
            telemetry=result.telemetry,
        )
