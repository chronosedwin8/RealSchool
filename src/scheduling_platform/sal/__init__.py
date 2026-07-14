"""Solver Abstraction Layer (SAL).

Interfaz ``ISolver`` y sus implementaciones. Esta es la ÚNICA capa del sistema
autorizada a importar ``ortools`` (u otro solver futuro). En la Fase 3 solo
vive el ``FakeSolver`` de pruebas; ``ORToolsSolver`` llegará en la Fase 7.
"""

from __future__ import annotations

from .fake_solver import FakeSolver, ImplicationRecord, LinearRecord
from .interface import (
    ISolver,
    Literal,
    RelOp,
    SolverConfig,
    SolverStatus,
    SolverVar,
)

__all__ = [
    "FakeSolver",
    "ISolver",
    "ImplicationRecord",
    "LinearRecord",
    "Literal",
    "RelOp",
    "SolverConfig",
    "SolverStatus",
    "SolverVar",
]
