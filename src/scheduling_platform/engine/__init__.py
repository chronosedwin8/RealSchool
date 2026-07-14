"""Motor, Optimizador y Telemetría (Fase 9).

Capa superior que cierra el circuito: ejecuta el pipeline, reconstruye el
horario desde las variables del solver (``SolutionBuilder``), explica su score
(``SolutionInspector``) y lo re-verifica con código independiente del solver
(``ValidationEngine``). El solver se inyecta como factory: esta capa no importa
``ortools``.
"""

from __future__ import annotations

from .engine import EngineResult, SchedulingEngine, SolverFactory
from .exceptions import EngineError, SolutionExtractionError
from .inspector import SolutionInspector, evaluate_linear
from .solution_builder import SolutionBuilder
from .validation import ValidationEngine, ValidationIssue, ValidationReport

__all__ = [
    "EngineError",
    "EngineResult",
    "SchedulingEngine",
    "SolutionBuilder",
    "SolutionExtractionError",
    "SolutionInspector",
    "SolverFactory",
    "ValidationEngine",
    "ValidationIssue",
    "ValidationReport",
    "evaluate_linear",
]
