"""Telemetría del pipeline de optimización.

Mide cada etapa por separado (análisis, lowering, pases, compilación al solver,
búsqueda, exportación) y la composición del modelo generado (variables por tipo,
intervalos, restricciones). Es la base de los benchmarks (Actividad 3) y de la
detección de regresiones de rendimiento.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Telemetry:
    """Latencias (ms), composición del modelo y estadísticas de búsqueda."""

    # --- Rendimiento por etapa (ms) ---
    t_analyze_ms: float = 0.0
    t_lower_ms: float = 0.0
    t_passes_ms: float = 0.0
    t_compile_ms: float = 0.0
    t_solve_ms: float = 0.0
    t_export_ms: float = 0.0
    t_total_ms: float = 0.0

    # --- Complejidad del modelo ---
    num_variables: int = 0
    num_constraints: int = 0
    num_constraints_before_passes: int = 0
    num_bool_vars: int = 0
    num_int_vars: int = 0
    num_continuous_vars: int = 0  # 0 en CP-SAT; el campo existe para los backends MIP
    num_intervals: int = 0

    # --- Configuración y estadísticas de búsqueda ---
    threads: int = 0
    num_branches: int = 0
    num_conflicts: int = 0
    t_first_solution_ms: int = 0  # tiempo a la primera solución factible (Actividad 10)

    @property
    def constraints_eliminated(self) -> int:
        """Restricciones que los Optimizer Passes lograron eliminar."""
        return max(0, self.num_constraints_before_passes - self.num_constraints)
