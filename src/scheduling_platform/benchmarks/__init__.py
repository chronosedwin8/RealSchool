"""Framework de benchmarking (Fase 11).

Datasets sintéticos parametrizables y un runner que recoge evidencia
cuantitativa (latencia por etapa, tamaño del modelo, memoria pico, calidad) para
medir el rendimiento del motor de forma reproducible y detectar regresiones.
"""

from __future__ import annotations

from .complexity import ComplexityReport, PowerLaw, analyze_scaling, fit_power_law
from .dashboard import build_dashboard_html, load_records
from .datasets import (
    LADDER_TEACHERS,
    LARGE,
    MEDIUM,
    PRESETS,
    SMALL,
    XL,
    DatasetSpec,
    InfeasibleDataset,
    build_academic,
    ladder_spec,
    ladder_specs,
)
from .record import DEFAULT_RESULTS_DIR, BenchmarkRecord, Provenance
from .resource_monitor import ResourceMonitor
from .runner import BenchmarkRun, BenchmarkRunner
from .stats import Stats, summarize, summarize_runs
from .suite import DEFAULT_REPS, ScenarioSpec, run_scenario

__all__ = [
    "DEFAULT_REPS",
    "DEFAULT_RESULTS_DIR",
    "LADDER_TEACHERS",
    "LARGE",
    "MEDIUM",
    "PRESETS",
    "SMALL",
    "XL",
    "BenchmarkRecord",
    "BenchmarkRun",
    "BenchmarkRunner",
    "ComplexityReport",
    "DatasetSpec",
    "InfeasibleDataset",
    "PowerLaw",
    "Provenance",
    "ResourceMonitor",
    "ScenarioSpec",
    "Stats",
    "analyze_scaling",
    "build_academic",
    "build_dashboard_html",
    "fit_power_law",
    "ladder_spec",
    "ladder_specs",
    "load_records",
    "run_scenario",
    "summarize",
    "summarize_runs",
]
