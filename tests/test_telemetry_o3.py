"""Telemetría completa (O3, Actividad 3): recursos, desglose de variables, ratios."""

from __future__ import annotations

from scheduling_platform.benchmarks import BenchmarkRunner, DatasetSpec
from scheduling_platform.benchmarks.resource_monitor import ResourceMonitor
from scheduling_platform.sal import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver

_TINY = DatasetSpec(
    name="tiny",
    teachers=10,
    rooms=8,
    groups=8,
    subjects=5,
    days=5,
    periods_per_day=6,
    load_factor=0.5,
)
_CONFIG = SolverConfig(max_time_in_seconds=20.0, num_search_workers=4, random_seed=1)


def test_resource_monitor_da_valores_sanos() -> None:
    with ResourceMonitor(interval_s=0.01) as monitor:
        total = sum(i * i for i in range(500_000))  # trabajo medible
    assert total > 0
    assert monitor.ram_peak_mb > 0
    assert monitor.ram_avg_mb > 0
    assert monitor.ram_peak_mb >= monitor.ram_avg_mb
    assert monitor.cpu_max_pct >= 0.0


def test_desglose_de_variables_cuadra() -> None:
    run = BenchmarkRunner(solver_factory=ORToolsSolver, boolean_starts=False).run(_TINY, _CONFIG)
    # En CP-SAT no hay continuas; toda variable es booleana o entera.
    assert run.num_continuous_vars == 0
    assert run.num_bool_vars + run.num_int_vars == run.num_variables
    assert run.num_bool_vars > 0 and run.num_int_vars > 0
    # El modo compacto modela el no-solape con intervalos.
    assert run.num_intervals > 0


def test_threads_reflejan_la_configuracion() -> None:
    run = BenchmarkRunner(solver_factory=ORToolsSolver).run(_TINY, _CONFIG)
    assert run.threads == 4


def test_ratios_de_escalabilidad_positivos() -> None:
    run = BenchmarkRunner(solver_factory=ORToolsSolver).run(_TINY, _CONFIG)
    assert run.ms_per_teacher > 0
    assert run.ms_per_group > 0
    assert run.ms_per_class > 0
    assert run.ms_per_variable > 0


def test_recursos_y_busqueda_registrados() -> None:
    run = BenchmarkRunner(solver_factory=ORToolsSolver).run(_TINY, _CONFIG)
    assert run.ram_peak_mb > 0
    assert run.t_export_ms >= 0
    # CP-SAT reporta ramas exploradas (>0 en una búsqueda con objetivo trivial o no).
    assert run.num_branches >= 0
    assert run.num_conflicts >= 0
    assert "docentes" in run.render()
