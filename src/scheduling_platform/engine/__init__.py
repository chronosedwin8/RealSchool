"""Motor, Métricas, ReOptimización y Simulación (Fases 9 y 10).

Capa superior que cierra el circuito: ejecuta el pipeline, reconstruye el
horario desde las variables del solver (``SolutionBuilder``), explica su score
(``SolutionInspector``), lo re-verifica con código independiente del solver
(``ValidationEngine``), calcula sus KPIs (``MetricsEngine``), permite congelar y
reoptimizar (``ReOptimizationEngine``) y evaluar escenarios what-if
(``SimulationEngine``). El solver se inyecta como factory: esta capa no importa
``ortools``.
"""

from __future__ import annotations

from .engine import EngineResult, SchedulingEngine, SolverFactory, warm_start_hints
from .exceptions import EngineError, SolutionExtractionError
from .inspector import SolutionInspector, evaluate_linear
from .metrics import MetricsComparison, MetricsEngine, ScheduleMetrics
from .reoptimization import ReOptimizationEngine, freeze_all_except
from .simulation import ScenarioOutcome, SimulationEngine, SimulationReport
from .solution_builder import SolutionBuilder
from .validation import ValidationEngine, ValidationIssue, ValidationReport

__all__ = [
    "EngineError",
    "EngineResult",
    "MetricsComparison",
    "MetricsEngine",
    "ReOptimizationEngine",
    "ScenarioOutcome",
    "ScheduleMetrics",
    "SchedulingEngine",
    "SimulationEngine",
    "SimulationReport",
    "SolutionBuilder",
    "SolutionExtractionError",
    "SolutionInspector",
    "SolverFactory",
    "ValidationEngine",
    "ValidationIssue",
    "ValidationReport",
    "evaluate_linear",
    "freeze_all_except",
    "warm_start_hints",
]
