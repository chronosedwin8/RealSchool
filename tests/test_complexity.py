"""Escalabilidad: escalera de datasets y complejidad observada (O6)."""

from __future__ import annotations

from scheduling_platform.benchmarks import (
    LADDER_TEACHERS,
    analyze_scaling,
    fit_power_law,
    ladder_spec,
    ladder_specs,
)


def test_la_escalera_es_factible_por_construccion() -> None:
    specs = ladder_specs()
    assert [s.teachers for s in specs] == list(LADDER_TEACHERS)
    for spec in specs:
        spec.validate()  # no lanza
    assert specs[-1].teachers == 500


def test_ladder_spec_mantiene_la_topologia() -> None:
    small = ladder_spec(20)
    big = ladder_spec(200)
    # aulas y grupos crecen en proporción con los docentes
    assert big.rooms > small.rooms
    assert big.groups > small.groups


def test_fit_power_law_recupera_el_exponente() -> None:
    xs = [1.0, 2.0, 4.0, 8.0, 16.0]
    ys = [3.0 * x**1.5 for x in xs]  # y = 3 * x^1.5
    law = fit_power_law(xs, ys)
    assert abs(law.exponent - 1.5) < 1e-6
    assert abs(law.coefficient - 3.0) < 1e-6
    assert law.r2 > 0.999


def test_clasificacion_por_exponente() -> None:
    assert fit_power_law([1, 2, 4], [1, 2, 4]).classification == "lineal"
    assert fit_power_law([1, 2, 4], [1, 4, 16]).classification == "cuadrático"
    lineal_log = fit_power_law([1, 2, 4, 8], [1.3, 2.8, 6.0, 13.0])
    assert lineal_log.classification in ("lineal", "casi-lineal (n·log n)")


def test_analyze_scaling_reporta_peor_etapa_propia() -> None:
    # etapa lineal vs etapa cuadrática: la peor propia debe ser la cuadrática
    runs = [
        {"teachers": 10, "t_lower_ms": 10.0, "t_compile_ms": 100.0, "t_solve_ms": 5.0},
        {"teachers": 20, "t_lower_ms": 20.0, "t_compile_ms": 400.0, "t_solve_ms": 5.0},
        {"teachers": 40, "t_lower_ms": 40.0, "t_compile_ms": 1600.0, "t_solve_ms": 5.0},
    ]
    report = analyze_scaling(runs, variable="teachers", metrics=("t_lower_ms", "t_compile_ms"))
    assert report.worst_stage == "t_compile_ms"
    assert abs(report.fits["t_lower_ms"].exponent - 1.0) < 0.05
    assert abs(report.fits["t_compile_ms"].exponent - 2.0) < 0.05
    assert "peor escala" in report.render()
