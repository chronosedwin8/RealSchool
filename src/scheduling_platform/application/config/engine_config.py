"""Configuración global del motor (``engine.yaml``), sin Pydantic.

Sigue el patrón del repo (dataclass congelada + ``validate()`` explícito, como
``DatasetSpec``): cero dependencia pesada nueva y mensajes de error hechos a
medida. Mapea a ``SolverConfig`` de la SAL.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...sal.interface import SolverConfig
from ..errors import ConfigError
from ..solvers import SOLVER_NAMES


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Parámetros globales del motor (solver por defecto, hilos, tiempo, semilla)."""

    version: str = "1.0.0"
    default_solver: str = "ortools_cpsat"
    threads: int = 8
    max_time_seconds: float = 600.0
    random_seed: int = 42

    def validate(self) -> None:
        if self.default_solver not in SOLVER_NAMES:
            raise ConfigError(
                f"engine.default_solver desconocido: {self.default_solver!r} "
                f"(opciones: {', '.join(SOLVER_NAMES)})"
            )
        if self.threads < 1:
            raise ConfigError(f"engine.threads debe ser >= 1: {self.threads}")
        if self.max_time_seconds <= 0:
            raise ConfigError(f"engine.max_time_seconds debe ser > 0: {self.max_time_seconds}")

    def to_solver_config(self) -> SolverConfig:
        """Traduce a la configuración de búsqueda de la SAL."""
        return SolverConfig(
            max_time_in_seconds=self.max_time_seconds,
            num_search_workers=self.threads,
            random_seed=self.random_seed,
        )
