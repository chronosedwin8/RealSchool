"""Estadística de benchmarking, registro automático y trazabilidad (O4)."""

from __future__ import annotations

import json
from pathlib import Path

from scheduling_platform.benchmarks import (
    DatasetSpec,
    Provenance,
    ScenarioSpec,
    Stats,
    run_scenario,
    summarize,
    summarize_runs,
)
from scheduling_platform.benchmarks.record import BenchmarkRecord
from scheduling_platform.benchmarks.stats import percentile, t_critical_95
from scheduling_platform.sal.interface import SolverConfig

_CONFIG = SolverConfig(max_time_in_seconds=15.0, num_search_workers=2, random_seed=1)


# --- Estadística ---


def test_summarize_valores_a_mano() -> None:
    stats = summarize([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert stats.n == 8
    assert stats.mean == 5.0
    assert stats.median == 4.5
    assert abs(stats.stdev - 2.138) < 0.01  # desv. muestral
    assert stats.minimum == 2.0
    assert stats.maximum == 9.0


def test_percentiles_por_interpolacion() -> None:
    valores = [1.0, 2.0, 3.0, 4.0]
    assert percentile(valores, 50) == 2.5
    assert percentile(valores, 0) == 1.0
    assert percentile(valores, 100) == 4.0


def test_intervalo_de_confianza_usa_t_de_student() -> None:
    # Muestra constante -> desviación 0 -> IC de ancho cero centrado en la media.
    stats = summarize([5.0, 5.0, 5.0, 5.0])
    assert stats.ci95_low == stats.ci95_high == 5.0
    # t crítico decrece con más grados de libertad y tiende a 1.96.
    assert t_critical_95(1) > t_critical_95(30) > 1.95
    assert t_critical_95(100) == 1.96


def test_summarize_runs_agrega_cada_metrica_numerica() -> None:
    runs = [
        {"dataset": "x", "solved": True, "t_total_ms": 10.0, "num_variables": 100},
        {"dataset": "x", "solved": True, "t_total_ms": 20.0, "num_variables": 100},
    ]
    agg = summarize_runs(runs)
    assert set(agg) == {"t_total_ms", "num_variables"}  # 'dataset' y 'solved' se excluyen
    assert isinstance(agg["t_total_ms"], Stats)
    assert agg["t_total_ms"].mean == 15.0


# --- Registro y trazabilidad ---


def test_provenance_captura_contexto() -> None:
    prov = Provenance.capture()
    assert prov.python_version
    assert prov.cpu_cores >= 1
    assert prov.ram_total_gb > 0
    assert "ortools" in prov.packages


def test_record_round_trip_json() -> None:
    prov = Provenance.capture()
    record = BenchmarkRecord(
        dataset="DS-Test",
        solver="CP-SAT",
        reps=2,
        warmup=1,
        config={"random_seed": 1},
        provenance=prov,
        aggregates={"t_total_ms": summarize([1.0, 2.0]).to_dict()},
        runs=[{"t_total_ms": 1.0}, {"t_total_ms": 2.0}],
        observaciones="prueba",
    )
    doc = json.loads(json.dumps(record.to_dict()))
    back = BenchmarkRecord.from_dict(doc)
    assert back.dataset == "DS-Test"
    assert back.reps == 2
    assert back.observaciones == "prueba"
    assert back.provenance.python_version == prov.python_version
    assert "Benchmark" in record.to_markdown()


def test_run_scenario_end_to_end_persiste(tmp_path: Path) -> None:
    tiny = DatasetSpec(name="DS-Tiny", teachers=8, rooms=6, groups=6, subjects=4, load_factor=0.5)
    scenario = ScenarioSpec(dataset=tiny, reps=2, warmup=1)
    record = run_scenario(scenario, _CONFIG)
    assert record.reps == 2
    assert "t_total_ms" in record.aggregates
    assert len(record.runs) == 2
    json_path = record.save(tmp_path)
    assert json_path.exists()
    assert json_path.with_suffix(".md").exists()
    reloaded = BenchmarkRecord.from_dict(json.loads(json_path.read_text(encoding="utf-8")))
    assert reloaded.dataset == "DS-Tiny"
