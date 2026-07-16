"""Optimization Pipeline (Fase 5).

Orquestación de las etapas pre-solver y de compilación: validación de
factibilidad (Constraint Graph Builder), explicación de conflictos
(Conflict Explanation Engine) y compilación del CIR al solver inyectado.
La resolución concreta, la extracción de la solución y las métricas llegan en
fases posteriores. No importa ``ortools``.
"""

from __future__ import annotations

from .conflict_explanation import ConflictExplanationEngine
from .events import ProgressCallback, ProgressEvent
from .graph_builder import ConstraintGraphBuilder
from .issues import ConflictReport, StructuralIssue
from .pipeline import OptimizationPipeline, PipelineResult
from .telemetry import Telemetry

__all__ = [
    "ConflictExplanationEngine",
    "ConflictReport",
    "ConstraintGraphBuilder",
    "OptimizationPipeline",
    "PipelineResult",
    "ProgressCallback",
    "ProgressEvent",
    "StructuralIssue",
    "Telemetry",
]
