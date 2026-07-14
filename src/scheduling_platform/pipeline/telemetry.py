"""Telemetría del pipeline de optimización.

Mide cada etapa por separado (análisis, lowering, pases, compilación al solver,
búsqueda) y el tamaño del modelo generado. Es la base de los benchmarks y de la
detección de regresiones de rendimiento.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Telemetry:
    """Latencias (ms) y tamaño del modelo de una corrida del pipeline."""

    t_analyze_ms: float = 0.0
    t_lower_ms: float = 0.0
    t_passes_ms: float = 0.0
    t_compile_ms: float = 0.0
    t_solve_ms: float = 0.0
    t_total_ms: float = 0.0
    num_variables: int = 0
    num_constraints: int = 0
    num_constraints_before_passes: int = 0

    @property
    def constraints_eliminated(self) -> int:
        """Restricciones que los Optimizer Passes lograron eliminar."""
        return max(0, self.num_constraints_before_passes - self.num_constraints)
