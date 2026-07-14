"""Constraint Intermediate Representation y Optimizer Passes (Fase 4).

Representación algebraica pura del problema, independiente del solver, con
pases de optimización (simplificación, deduplicación, fusión, detección de
contradicciones, reordenamiento). Flujo del pipeline de compilación:
``DSL -> lower -> CIR -> PassManager -> CirToSolverCompiler -> ISolver``.
Prohibido importar ``ortools`` aquí.
"""

from __future__ import annotations

from .compiler import CirToSolverCompiler
from .evaluation import constraint_holds, satisfies
from .exceptions import CirError, StructuralContradictionError
from .lowering import lower
from .nodes import (
    CirAllDifferent,
    CirBoolOr,
    CirConstraint,
    CirImplication,
    CirIntervalSpec,
    CirLinear,
    CirLiteral,
    CirModel,
    CirNoOverlap,
    CirObjective,
)
from .passes import (
    CirPass,
    DeduplicateConstraints,
    DetectContradictions,
    FuseComparableLinear,
    PassManager,
    RemoveTrivialConstraints,
    ReorderForPropagation,
    SimplifyLinearByGcd,
)
from .serialization import cir_to_text

__all__ = [
    "CirAllDifferent",
    "CirBoolOr",
    "CirConstraint",
    "CirError",
    "CirImplication",
    "CirIntervalSpec",
    "CirLinear",
    "CirLiteral",
    "CirModel",
    "CirNoOverlap",
    "CirObjective",
    "CirPass",
    "CirToSolverCompiler",
    "DeduplicateConstraints",
    "DetectContradictions",
    "FuseComparableLinear",
    "PassManager",
    "RemoveTrivialConstraints",
    "ReorderForPropagation",
    "SimplifyLinearByGcd",
    "StructuralContradictionError",
    "cir_to_text",
    "constraint_holds",
    "lower",
    "satisfies",
]
