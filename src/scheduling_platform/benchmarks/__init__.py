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
from .record import DEFAULT_RESULTS_DIR, BenchmarkRecord, Provenance
from .resource_monitor import ResourceMonitor
from .runner import BenchmarkRun, BenchmarkRunner
from .stats import Stats, summarize, summarize_runs
from .suite import DEFAULT_REPS, ScenarioSpec, run_scenario

__all__ = [
    "DEFAULT_REPS",
    "DEFAULT_RESULTS_DIR",
    "LARGE",
    "MEDIUM",
    "PRESETS",
    "SMALL",
    "XL",
    "BenchmarkRecord",
    "BenchmarkRun",
    "BenchmarkRunner",
    "DatasetSpec",
    "InfeasibleDataset",
    "Provenance",
    "ResourceMonitor",
    "ScenarioSpec",
    "Stats",
    "build_academic",
    "run_scenario",
    "summarize",
    "summarize_runs",
]
