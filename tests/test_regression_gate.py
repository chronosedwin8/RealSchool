"""Gate de regresiones (O8, Actividades 8 y 11)."""

from __future__ import annotations

from typing import Any

from scheduling_platform.benchmarks import Thresholds, compare, render_report


def _doc(
    *, t_p50: float, ram: float, score: float, conflicts: float = 0.0, hard: float = 0.0
) -> dict[str, Any]:
    return {
        "dataset": "DS-Test",
        "aggregates": {
            "t_total_ms": {"p50": t_p50, "mean": t_p50},
            "ram_peak_mb": {"mean": ram},
            "quality_score": {"mean": score},
            "num_conflicts": {"mean": conflicts},
            "hard_violations": {"mean": hard},
        },
    }


_BASELINE = _doc(t_p50=1000.0, ram=100.0, score=95.0, conflicts=50.0)


def test_sin_cambios_no_hay_regresion() -> None:
    assert compare(_BASELINE, _BASELINE) == []


def test_mejora_no_es_regresion() -> None:
    mejor = _doc(t_p50=800.0, ram=90.0, score=97.0, conflicts=40.0)
    assert compare(_BASELINE, mejor) == []


def test_tiempo_por_encima_del_umbral_falla() -> None:
    # +6% en P50 supera el umbral del 5%
    peor = _doc(t_p50=1060.0, ram=100.0, score=95.0)
    violaciones = compare(_BASELINE, peor)
    assert any("t_total" in v.metric for v in violaciones)


def test_tiempo_dentro_del_umbral_pasa() -> None:
    # +4% en P50 está dentro del 5%
    ok = _doc(t_p50=1040.0, ram=100.0, score=95.0, conflicts=50.0)
    assert compare(_BASELINE, ok) == []


def test_ram_por_encima_del_umbral_falla() -> None:
    peor = _doc(t_p50=1000.0, ram=120.0, score=95.0)  # +20% > 10%
    assert any("ram" in v.metric for v in compare(_BASELINE, peor))


def test_score_a_la_baja_falla() -> None:
    peor = _doc(t_p50=1000.0, ram=100.0, score=93.0)
    assert any("score" in v.metric for v in compare(_BASELINE, peor))


def test_conflictos_al_alza_falla() -> None:
    peor = _doc(t_p50=1000.0, ram=100.0, score=95.0, conflicts=100.0)  # +100% > 20%
    assert any("conflicts" in v.metric for v in compare(_BASELINE, peor))


def test_violacion_dura_falla_siempre() -> None:
    peor = _doc(t_p50=1000.0, ram=100.0, score=95.0, hard=1.0)
    violaciones = compare(_BASELINE, peor)
    assert any("hard_violations" in v.metric for v in violaciones)


def test_umbral_configurable() -> None:
    peor = _doc(t_p50=1060.0, ram=100.0, score=95.0)  # +6%
    assert compare(_BASELINE, peor, Thresholds(t_total_pct=10.0)) == []  # ahora tolera hasta 10%


def test_informe_pass_y_fail() -> None:
    assert "PASS" in render_report([("DS-Test", [])])
    peor = _doc(t_p50=2000.0, ram=100.0, score=95.0)
    fail = render_report([("DS-Test", compare(_BASELINE, peor))])
    assert "FAIL" in fail
    assert "t_total" in fail
