"""Detección de regresiones entre versiones del motor (Actividades 8 y 11).

Compara el registro de un benchmark contra su *baseline* y falla si alguna
métrica empeora más allá del umbral: P50 de ``t_total`` sube > 5 %, ``ram_peak``
sube > 10 %, el ``score`` baja, los conflictos suben o hay violaciones duras.
Convierte el benchmarking en una prueba de calidad continua: una optimización
local que degrada el comportamiento global no se incorpora sin justificarse.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Umbrales de tolerancia del gate (Actividad 8)."""

    t_total_pct: float = 5.0  # P50 de t_total puede subir como mucho un 5 %
    ram_pct: float = 10.0  # ram_peak puede subir como mucho un 10 %
    conflicts_pct: float = 20.0  # margen para el ruido de la búsqueda paralela
    score_epsilon: float = 0.01  # el score no puede bajar más de esto


@dataclass(frozen=True, slots=True)
class Violation:
    """Una métrica que empeoró más allá de su umbral."""

    metric: str
    baseline: float
    candidate: float
    detail: str

    def render(self) -> str:
        return f"{self.metric}: {self.baseline:.2f} -> {self.candidate:.2f} ({self.detail})"


def _agg(doc: Mapping[str, Any], metric: str, field: str) -> float | None:
    stats = doc.get("aggregates", {}).get(metric)
    if not stats or field not in stats:
        return None
    return float(stats[field])


def compare(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    thresholds: Thresholds | None = None,
) -> list[Violation]:
    """Lista de regresiones del candidato frente al baseline (vacía = todo OK)."""
    t = thresholds or Thresholds()
    violations: list[Violation] = []

    b_t = _agg(baseline, "t_total_ms", "p50")
    c_t = _agg(candidate, "t_total_ms", "p50")
    if b_t is not None and c_t is not None and b_t > 0 and c_t > b_t * (1 + t.t_total_pct / 100):
        violations.append(
            Violation(
                "t_total_ms (P50)", b_t, c_t, f"+{100 * (c_t - b_t) / b_t:.1f}% > {t.t_total_pct}%"
            )
        )

    b_r = _agg(baseline, "ram_peak_mb", "mean")
    c_r = _agg(candidate, "ram_peak_mb", "mean")
    if b_r is not None and c_r is not None and b_r > 0 and c_r > b_r * (1 + t.ram_pct / 100):
        violations.append(
            Violation("ram_peak_mb", b_r, c_r, f"+{100 * (c_r - b_r) / b_r:.1f}% > {t.ram_pct}%")
        )

    b_s = _agg(baseline, "quality_score", "mean")
    c_s = _agg(candidate, "quality_score", "mean")
    if b_s is not None and c_s is not None and c_s < b_s - t.score_epsilon:
        violations.append(Violation("quality_score", b_s, c_s, "el score bajó"))

    b_c = _agg(baseline, "num_conflicts", "mean")
    c_c = _agg(candidate, "num_conflicts", "mean")
    if b_c is not None and c_c is not None and b_c > 0 and c_c > b_c * (1 + t.conflicts_pct / 100):
        violations.append(
            Violation(
                "num_conflicts", b_c, c_c, f"+{100 * (c_c - b_c) / b_c:.1f}% > {t.conflicts_pct}%"
            )
        )

    c_h = _agg(candidate, "hard_violations", "mean")
    if c_h is not None and c_h > 0:
        violations.append(Violation("hard_violations", 0.0, c_h, "el horario dejó de ser válido"))

    return violations


def render_report(results: Sequence[tuple[str, list[Violation]]]) -> str:
    """Informe Markdown de diferencias por dataset (Actividad 11)."""
    lines = ["# Informe de regresiones", ""]
    total = sum(len(v) for _, v in results)
    if total == 0:
        lines.append("**PASS** — ninguna métrica empeoró más allá de su umbral.")
        return "\n".join(lines) + "\n"
    lines.append(f"**FAIL** — {total} regresión(es) detectada(s).")
    for dataset, violations in results:
        if not violations:
            continue
        lines += ["", f"## {dataset}", ""]
        lines += [f"- {v.render()}" for v in violations]
    return "\n".join(lines) + "\n"
