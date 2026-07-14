"""Framework de benchmarking (Fase 11).

Datasets sintéticos parametrizables y un runner que recoge evidencia
cuantitativa (latencia por etapa, tamaño del modelo, memoria pico, calidad) para
medir el rendimiento del motor de forma reproducible y detectar regresiones.
"""

from __future__ import annotations

from .datasets import (
    LARGE,
    MEDIUM,
    PRESETS,
    SMALL,
    XL,
    DatasetSpec,
    InfeasibleDataset,
    build_academic,
)
from .runner import BenchmarkRun, BenchmarkRunner

__all__ = [
    "LARGE",
    "MEDIUM",
    "PRESETS",
    "SMALL",
    "XL",
    "BenchmarkRun",
    "BenchmarkRunner",
    "DatasetSpec",
    "InfeasibleDataset",
    "build_academic",
]
