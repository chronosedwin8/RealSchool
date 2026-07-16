"""Resolución de nombres de solver a factories de ``ISolver`` (composición).

La configuración (``engine.yaml``) y los flags (``--solver``) nombran el backend
con una cadena estable; aquí se traduce a la factory concreta de la SAL. Es la
Capa de Aplicación la que conoce ambos solvers (CP-SAT y los MILP), no el Core.
"""

from __future__ import annotations

from functools import partial

from ..engine import SolverFactory
from ..sal.mip_solver import MipSolver
from ..sal.ortools_solver import ORToolsSolver
from .errors import ConfigError

#: Nombre de configuración -> factory de ``ISolver``.
SOLVER_FACTORIES: dict[str, SolverFactory] = {
    "ortools_cpsat": ORToolsSolver,
    "cbc": partial(MipSolver, "CBC"),
    "scip": partial(MipSolver, "SCIP"),
    "highs": partial(MipSolver, "HiGHS"),
}

SOLVER_NAMES: tuple[str, ...] = tuple(SOLVER_FACTORIES)


def solver_factory_for(name: str) -> SolverFactory:
    """Devuelve la factory del solver ``name`` o falla con un error de config."""
    try:
        return SOLVER_FACTORIES[name]
    except KeyError:
        raise ConfigError(
            f"solver desconocido: {name!r} (opciones: {', '.join(SOLVER_NAMES)})"
        ) from None
