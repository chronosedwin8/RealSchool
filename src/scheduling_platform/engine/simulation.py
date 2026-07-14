"""Simulation Engine: escenarios "what-if" en modo sandbox.

Responde preguntas del tipo "¿y si contrato otro docente?" o "¿y si habilito un
aula más?": resuelve la línea base y el escenario, calcula los KPIs de ambos y
los compara. No modifica nada: cada escenario es un problema canónico distinto.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..core.problem import SchedulingProblem
from ..plugins.base import SchedulingPlugin
from ..plugins.registry import registry_with
from ..sal.interface import SolverConfig
from .engine import EngineResult, SchedulingEngine, SolverFactory
from .metrics import MetricsComparison, MetricsEngine, ScheduleMetrics


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """Resultado de un escenario: qué salió y qué tan bueno fue."""

    name: str
    result: EngineResult
    metrics: ScheduleMetrics | None

    @property
    def feasible(self) -> bool:
        return self.result.solved


@dataclass(frozen=True, slots=True)
class SimulationReport:
    """Comparación entre la línea base y un escenario alternativo."""

    baseline: ScenarioOutcome
    scenario: ScenarioOutcome

    @property
    def comparison(self) -> MetricsComparison | None:
        if self.baseline.metrics is None or self.scenario.metrics is None:
            return None
        return MetricsComparison(baseline=self.baseline.metrics, candidate=self.scenario.metrics)

    def render(self) -> str:
        lines = [f"Línea base ({self.baseline.name}): "]
        lines[0] += "factible" if self.baseline.feasible else "INFACTIBLE"
        lines.append(
            f"Escenario ({self.scenario.name}): "
            + ("factible" if self.scenario.feasible else "INFACTIBLE")
        )
        comparison = self.comparison
        if comparison is not None:
            lines.append(comparison.render())
        elif self.scenario.feasible and not self.baseline.feasible:
            lines.append("El escenario vuelve factible un problema que no tenía solución.")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class SimulationEngine:
    """Evalúa escenarios alternativos y los compara con la línea base."""

    plugins: Sequence[SchedulingPlugin]
    solver_factory: SolverFactory
    metrics: MetricsEngine = field(default_factory=MetricsEngine)

    def run_scenario(
        self,
        name: str,
        problem: SchedulingProblem,
        config: SolverConfig | None = None,
    ) -> ScenarioOutcome:
        engine = SchedulingEngine(
            registry=registry_with(list(self.plugins)), solver_factory=self.solver_factory
        )
        result = engine.solve(problem, config)
        metrics = (
            self.metrics.compute(problem, result.solution) if result.solution is not None else None
        )
        return ScenarioOutcome(name=name, result=result, metrics=metrics)

    def compare(
        self,
        baseline: SchedulingProblem,
        scenario: SchedulingProblem,
        *,
        baseline_name: str = "actual",
        scenario_name: str = "what-if",
        config: SolverConfig | None = None,
    ) -> SimulationReport:
        return SimulationReport(
            baseline=self.run_scenario(baseline_name, baseline, config),
            scenario=self.run_scenario(scenario_name, scenario, config),
        )
