"""Orquestador de escenarios de benchmarking (Actividades 4 y 5).

Ejecuta un escenario N veces (con corridas de calentamiento descartadas), agrega
las métricas con estadística (:mod:`stats`) y empaqueta todo en un
:class:`BenchmarkRecord` trazable que se persiste automáticamente.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..engine import SolverFactory
from ..plugins.base import SchedulingPlugin
from ..sal.interface import SolverConfig
from ..sal.ortools_solver import ORToolsSolver
from .datasets import DatasetSpec
from .record import BenchmarkRecord, Provenance
from .runner import BenchmarkRunner
from .stats import summarize_runs

#: Repeticiones por defecto según el tamaño (escalonadas: reduce ruido sin coste
#: prohibitivo en las instancias grandes).
DEFAULT_REPS: dict[str, int] = {"small": 20, "medium": 10, "large": 5, "xl": 3}


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    """Un escenario a medir: dataset + cuántas veces + con qué solver."""

    dataset: DatasetSpec
    reps: int
    warmup: int = 2
    solver_name: str = "CP-SAT"
    boolean_starts: bool = False


def run_scenario(
    scenario: ScenarioSpec,
    config: SolverConfig,
    *,
    solver_factory: SolverFactory = ORToolsSolver,
    plugins: Sequence[SchedulingPlugin] | None = None,
    observaciones: str = "",
) -> BenchmarkRecord:
    """Ejecuta el escenario y devuelve su registro agregado (aún sin persistir)."""
    if plugins is not None:
        runner = BenchmarkRunner(
            solver_factory=solver_factory,
            plugins=plugins,
            boolean_starts=scenario.boolean_starts,
        )
    else:
        runner = BenchmarkRunner(
            solver_factory=solver_factory, boolean_starts=scenario.boolean_starts
        )

    for _ in range(scenario.warmup):
        runner.run(scenario.dataset, config)  # calentamiento: descartado

    runs = [runner.run(scenario.dataset, config).to_dict() for _ in range(scenario.reps)]
    aggregates = {key: stats.to_dict() for key, stats in summarize_runs(runs).items()}

    config_dict = {
        "max_time_in_seconds": config.max_time_in_seconds,
        "num_search_workers": config.num_search_workers,
        "random_seed": config.random_seed,
        "solver": scenario.solver_name,
    }
    return BenchmarkRecord(
        dataset=scenario.dataset.name,
        solver=scenario.solver_name,
        reps=scenario.reps,
        warmup=scenario.warmup,
        config=config_dict,
        provenance=Provenance.capture(),
        aggregates=aggregates,
        runs=runs,
        observaciones=observaciones,
    )
