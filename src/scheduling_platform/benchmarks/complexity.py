"""Análisis de complejidad observada (Actividad 9).

Ajusta una ley de potencias ``y = a·x^b`` por mínimos cuadrados en escala
log-log a la escalera de datasets crecientes, para estimar el **exponente de
crecimiento** de cada etapa del pipeline (adaptación, lowering, pases,
compilación, búsqueda) frente al número de docentes/clases/variables. Así se
clasifica el crecimiento (lineal / n·log n / cuadrático / superior) y se
identifica la etapa que peor escala **antes** de llegar a instituciones enormes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# Métricas de tiempo por etapa que interesa perfilar frente a la escala.
STAGE_METRICS: tuple[str, ...] = (
    "t_adaptation_ms",
    "t_build_model_ms",
    "t_lower_ms",
    "t_passes_ms",
    "t_compile_ms",
    "t_solve_ms",
    "t_total_ms",
)


@dataclass(frozen=True, slots=True)
class PowerLaw:
    """Ajuste ``y = coefficient · x^exponent`` con su bondad ``r2``."""

    exponent: float
    coefficient: float
    r2: float
    n_points: int

    @property
    def classification(self) -> str:
        """Etiqueta cualitativa del crecimiento según el exponente."""
        b = self.exponent
        if b < 0.2:
            return "constante"
        if b <= 1.15:
            return "lineal"
        if b <= 1.4:
            return "casi-lineal (n·log n)"
        if b <= 2.3:
            return "cuadrático"
        return "polinómico alto / super-cuadrático"


def fit_power_law(xs: Sequence[float], ys: Sequence[float]) -> PowerLaw:
    """Ajusta ``y = a·x^b`` por regresión lineal de ``log y`` sobre ``log x``."""
    points = [(math.log(x), math.log(y)) for x, y in zip(xs, ys, strict=False) if x > 0 and y > 0]
    n = len(points)
    if n < 2:
        return PowerLaw(exponent=0.0, coefficient=0.0, r2=0.0, n_points=n)

    mean_x = sum(px for px, _ in points) / n
    mean_y = sum(py for _, py in points) / n
    sxx = sum((px - mean_x) ** 2 for px, _ in points)
    sxy = sum((px - mean_x) * (py - mean_y) for px, py in points)
    if sxx == 0:
        return PowerLaw(exponent=0.0, coefficient=0.0, r2=0.0, n_points=n)

    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    syy = sum((py - mean_y) ** 2 for _, py in points)
    ss_res = sum((py - (intercept + slope * px)) ** 2 for px, py in points)
    r2 = 1.0 - ss_res / syy if syy > 0 else 1.0
    return PowerLaw(exponent=slope, coefficient=math.exp(intercept), r2=r2, n_points=n)


@dataclass(frozen=True, slots=True)
class ComplexityReport:
    """Exponentes observados de cada métrica frente a una variable de escala."""

    variable: str  # p. ej. "teachers"
    fits: dict[str, PowerLaw]

    @property
    def worst_stage(self) -> str:
        """Etapa propia (excluye la búsqueda del solver) que peor escala."""
        own = {k: v for k, v in self.fits.items() if k not in ("t_solve_ms", "t_total_ms")}
        if not own:
            return ""
        return max(own, key=lambda k: own[k].exponent)

    def render(self) -> str:
        lines = [f"Complejidad observada frente a '{self.variable}':"]
        for metric, law in sorted(self.fits.items(), key=lambda kv: -kv[1].exponent):
            lines.append(
                f"  {metric:<20} exponente {law.exponent:5.2f}  "
                f"({law.classification}, r²={law.r2:.3f})"
            )
        if self.worst_stage:
            lines.append(f"  -> etapa propia que peor escala: {self.worst_stage}")
        return "\n".join(lines)


def analyze_scaling(
    runs: Sequence[dict[str, float]],
    variable: str = "teachers",
    metrics: Sequence[str] = STAGE_METRICS,
) -> ComplexityReport:
    """Estima el exponente de cada métrica frente a ``variable`` sobre la escalera."""
    xs = [float(run[variable]) for run in runs]
    fits: dict[str, PowerLaw] = {}
    for metric in metrics:
        ys = [float(run.get(metric, 0.0)) for run in runs]
        fits[metric] = fit_power_law(xs, ys)
    return ComplexityReport(variable=variable, fits=fits)
