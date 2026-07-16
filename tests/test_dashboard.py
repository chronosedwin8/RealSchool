"""Dashboard HTML estático (O7): genera HTML válido y tolera datos parciales."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scheduling_platform.benchmarks import build_dashboard_html, load_records


def _record(
    dataset: str, solver: str, commit: str, t_mean: float, runs: list[float]
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "solver": solver,
        "reps": len(runs),
        "provenance": {
            "git_commit": commit,
            "timestamp_iso": "2026-07-16T10:00:00+00:00",
            "cpu_cores": 8,
            "ram_total_gb": 16.0,
        },
        "aggregates": {
            "t_total_ms": {"mean": t_mean, "median": t_mean, "p95": t_mean},
            "quality_score": {"mean": 95.0},
        },
        "runs": [{"t_total_ms": v} for v in runs],
    }


def test_pagina_vacia_es_valida() -> None:
    html = build_dashboard_html([])
    assert html.startswith("<!doctype html>")
    assert "No hay registros" in html
    assert html.count("<html") == 1 and "</html>" in html


def test_dashboard_incluye_todas_las_graficas() -> None:
    records = [
        _record("DS-01", "CP-SAT", "aaaa111", 1000.0, [980.0, 1010.0, 1000.0]),
        _record("DS-01", "CBC", "aaaa111", 3000.0, [2900.0, 3100.0]),
        _record("DS-02", "CP-SAT", "bbbb222", 2000.0, [1950.0, 2050.0]),
    ]
    html = build_dashboard_html(records)
    assert html.startswith("<!doctype html>")
    # secciones pedidas por la Actividad 6
    for titulo in (
        "Corridas registradas",
        "Tiempo total por versión",
        "Comparación de solvers",
        "boxplot",
        "Histograma",
        "Heatmap",
    ):
        assert titulo in html
    assert "<svg" in html  # gráficas SVG inline
    assert "prefers-color-scheme" in html  # tema claro/oscuro
    assert "http://" not in html and "https://" not in html.replace("lang=", "")  # autocontenido


def test_tolera_registro_sin_metricas() -> None:
    parcial = {
        "dataset": "DS-X",
        "solver": "CP-SAT",
        "reps": 0,
        "provenance": {"git_commit": "c0ffee", "timestamp_iso": "2026-07-16T09:00:00+00:00"},
        "aggregates": {},
        "runs": [],
    }
    html = build_dashboard_html([parcial])  # no debe lanzar
    assert "DS-X" in html
    assert "—" in html  # celdas sin métrica


def test_load_records_lee_y_ordena(tmp_path: Path) -> None:
    (tmp_path / "b.json").write_text(
        json.dumps(_record("DS-2", "CP-SAT", "b", 2.0, [2.0])), encoding="utf-8"
    )
    (tmp_path / "a.json").write_text(
        json.dumps(_record("DS-1", "CP-SAT", "a", 1.0, [1.0])), encoding="utf-8"
    )
    (tmp_path / "ladder.json").write_text("{}", encoding="utf-8")  # se ignora
    (tmp_path / "roto.json").write_text("no-json{", encoding="utf-8")  # se tolera
    records = load_records(tmp_path)
    assert len(records) == 2  # ladder y roto excluidos
    assert {r["dataset"] for r in records} == {"DS-1", "DS-2"}
