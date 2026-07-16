"""Estadística de benchmarking (Actividad 4).

Ejecuta cada escenario N veces y resume cada métrica con media, mediana,
desviación estándar, mínimo, máximo, percentiles (P50/P95/P99) e intervalo de
confianza al 95 % (t de Student). Repetir y agregar reduce el ruido del SO y la
varianza térmica del hardware.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

# Valor crítico t de Student para IC bilateral al 95 % (t_{0.975}) por grados de
# libertad. Para df > 30 se usa la aproximación normal 1.96.
_T_975: dict[int, float] = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def t_critical_95(df: int) -> float:
    """Valor crítico t de Student al 95 % para ``df`` grados de libertad."""
    if df <= 0:
        return 0.0
    return _T_975.get(df, 1.96)


def percentile(values: Sequence[float], p: float) -> float:
    """Percentil ``p`` (0-100) por interpolación lineal (método de NumPy)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    frac = rank - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


@dataclass(frozen=True, slots=True)
class Stats:
    """Resumen estadístico de una métrica sobre N repeticiones."""

    n: int
    mean: float
    median: float
    stdev: float
    minimum: float
    maximum: float
    p50: float
    p95: float
    p99: float
    ci95_low: float
    ci95_high: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self, unit: str = "") -> str:
        suf = f" {unit}" if unit else ""
        return (
            f"media {self.mean:.2f}{suf} · mediana {self.median:.2f} · "
            f"sd {self.stdev:.2f} · [{self.minimum:.2f}, {self.maximum:.2f}] · "
            f"P95 {self.p95:.2f} · IC95 [{self.ci95_low:.2f}, {self.ci95_high:.2f}]"
        )


def summarize(values: Sequence[float]) -> Stats:
    """Resume una muestra en un :class:`Stats` (media, percentiles, IC95...)."""
    if not values:
        raise ValueError("no se puede resumir una muestra vacía")
    n = len(values)
    mean = statistics.fmean(values)
    median = statistics.median(values)
    stdev = statistics.stdev(values) if n > 1 else 0.0
    margin = t_critical_95(n - 1) * stdev / math.sqrt(n) if n > 1 else 0.0
    return Stats(
        n=n,
        mean=mean,
        median=median,
        stdev=stdev,
        minimum=min(values),
        maximum=max(values),
        p50=percentile(values, 50),
        p95=percentile(values, 95),
        p99=percentile(values, 99),
        ci95_low=mean - margin,
        ci95_high=mean + margin,
    )


def summarize_runs(runs: Sequence[dict[str, Any]]) -> dict[str, Stats]:
    """Resume cada métrica numérica común a todas las corridas.

    Recibe la lista de ``BenchmarkRun.to_dict()`` y devuelve, por cada campo
    numérico (int/float, salvo booleanos), su :class:`Stats` agregado.
    """
    if not runs:
        return {}
    numeric_keys = [
        key
        for key, value in runs[0].items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    result: dict[str, Stats] = {}
    for key in numeric_keys:
        values = [float(run[key]) for run in runs if key in run]
        if values:
            result[key] = summarize(values)
    return result
