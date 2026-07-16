"""Generador de dashboard HTML estático y autocontenido (Actividad 6).

Lee los registros JSON de ``benchmarks/results/`` y produce una sola página HTML
**sin dependencias externas** (CSS inline, gráficas como **SVG generado en
Python** -- sin JS ni CDNs), con tema claro/oscuro. Incluye las gráficas pedidas:
líneas (tiempo/score por versión), barras (comparación de solvers), boxplots
(dispersión entre repeticiones), histogramas, heatmap (dataset x solver) y una
tabla de corridas con commit y hardware.

Generar SVG desde Python (en vez de un motor JS de gráficas) hace la salida
determinista y testeable, y garantiza el autocontenido.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Paleta accesible (funciona en claro y oscuro), por índice de serie.
_PALETTE = ("#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#14b8a6")
_W, _H, _PAD = 640, 260, 44


def load_records(results_dir: Path) -> list[dict[str, Any]]:
    """Carga todos los registros JSON de la carpeta (ordenados por fecha)."""
    records: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.json")):
        if path.name == "ladder.json":
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if "aggregates" in doc and "dataset" in doc:
            records.append(doc)
    records.sort(key=lambda d: d.get("provenance", {}).get("timestamp_iso", ""))
    return records


def _mean(record: dict[str, Any], metric: str) -> float | None:
    agg = record.get("aggregates", {}).get(metric)
    return float(agg["mean"]) if agg and "mean" in agg else None


# --- primitivas SVG (mantienen las líneas cortas y sin duplicación) ---


def _text(x: float, y: float, cls: str, txt: str, anchor: str = "middle") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="{cls}">{txt}</text>'


def _rect(x: float, y: float, w: float, h: float, attrs: str) -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" {attrs}/>'


def _line(x1: float, y1: float, x2: float, y2: float, attrs: str) -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" {attrs}/>'


def _svg(body: str, width: int = _W, height: int = _H) -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" preserveAspectRatio="xMidYMid meet">{body}</svg>'
    )


def _axis(width: int = _W, height: int = _H) -> str:
    return _line(_PAD, height - _PAD, width - 5, height - _PAD, 'class="axis"') + _line(
        _PAD, 5, _PAD, height - _PAD, 'class="axis"'
    )


def _empty() -> str:
    return "<p class='muted'>sin datos</p>"


def _bars(labels: Sequence[str], values: Sequence[float], unit: str = "ms") -> str:
    if not values:
        return _empty()
    top = max(values) or 1.0
    gap = (_W - _PAD - 10) / max(len(values), 1)
    bw = gap * 0.6
    body = [_axis()]
    for i, (label, value) in enumerate(zip(labels, values, strict=False)):
        x = _PAD + i * gap + (gap - bw) / 2
        bh = (_H - 2 * _PAD) * (value / top)
        y = _H - _PAD - bh
        color = _PALETTE[i % len(_PALETTE)]
        body.append(_rect(x, y, bw, bh, f'fill="{color}"'))
        body.append(_text(x + bw / 2, y - 4, "lbl", f"{value:.0f}"))
        body.append(_text(x + bw / 2, _H - _PAD + 16, "tick", html.escape(label)))
    body.append(_text(_PAD, 16, "tick", unit, anchor="start"))
    return _svg("".join(body))


def _lines(labels: Sequence[str], series: dict[str, Sequence[float | None]], unit: str) -> str:
    todos = [v for vals in series.values() for v in vals if v is not None]
    if not todos:
        return _empty()
    top = max(todos) or 1.0
    step = (_W - _PAD - 10) / max(len(labels) - 1, 1)
    body = [_axis()]
    for si, vals in enumerate(series.values()):
        color = _PALETTE[si % len(_PALETTE)]
        pts = []
        for i, v in enumerate(vals):
            if v is None:
                continue
            x = _PAD + i * step
            y = _H - _PAD - (_H - 2 * _PAD) * (v / top)
            pts.append(f"{x:.1f},{y:.1f}")
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
        if pts:
            joined = " ".join(pts)
            body.append(
                f'<polyline points="{joined}" fill="none" stroke="{color}" stroke-width="2"/>'
            )
    for i, label in enumerate(labels):
        body.append(_text(_PAD + i * step, _H - _PAD + 16, "tick", html.escape(label)))
    body.append(_text(_PAD, 16, "tick", unit, anchor="start"))
    keys = " ".join(
        f'<span class="key"><i style="background:{_PALETTE[si % len(_PALETTE)]}"></i>'
        f"{html.escape(name)}</span>"
        for si, name in enumerate(series)
    )
    return _svg("".join(body)) + f'<div class="legend">{keys}</div>'


def _boxplots(labels: Sequence[str], samples: Sequence[Sequence[float]]) -> str:
    data = [(lbl, sorted(s)) for lbl, s in zip(labels, samples, strict=False) if s]
    if not data:
        return _empty()
    top = max(v for _, s in data for v in s) or 1.0
    gap = (_W - _PAD - 10) / max(len(data), 1)

    def y_of(v: float) -> float:
        return _H - _PAD - (_H - 2 * _PAD) * (v / top)

    body = [_axis()]
    for i, (label, s) in enumerate(data):
        cx = _PAD + i * gap + gap / 2
        q1, med, q3 = _percentile(s, 25), _percentile(s, 50), _percentile(s, 75)
        color = _PALETTE[i % len(_PALETTE)]
        bw = gap * 0.4
        body.append(_line(cx, y_of(s[0]), cx, y_of(s[-1]), 'class="axis"'))
        fill = f'fill="{color}" fill-opacity="0.5" stroke="{color}"'
        body.append(_rect(cx - bw / 2, y_of(q3), bw, max(1, y_of(q1) - y_of(q3)), fill))
        body.append(
            _line(
                cx - bw / 2, y_of(med), cx + bw / 2, y_of(med), f'stroke="{color}" stroke-width="2"'
            )
        )
        body.append(_text(cx, _H - _PAD + 16, "tick", html.escape(label)))
    return _svg("".join(body))


def _histogram(values: Sequence[float], bins: int = 10) -> str:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return "<p class='muted'>sin datos suficientes</p>"
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1
    width_bin = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        idx = min(bins - 1, int((v - lo) / width_bin))
        counts[idx] += 1
    labels = [f"{lo + i * width_bin:.0f}" for i in range(bins)]
    return _bars(labels, [float(c) for c in counts], unit="conteo")


def _heatmap(
    datasets: Sequence[str], solvers: Sequence[str], grid: dict[tuple[str, str], float]
) -> str:
    if not grid:
        return _empty()
    cell, padx, pady = 90, 130, 24
    width = padx + len(solvers) * cell + 10
    height = pady + len(datasets) * 34 + 10
    top = max(grid.values()) or 1.0
    body = []
    for ci, solver in enumerate(solvers):
        body.append(_text(padx + ci * cell + cell / 2, 16, "tick", html.escape(solver)))
    for ri, dataset in enumerate(datasets):
        y = pady + ri * 34
        body.append(_text(4, y + 22, "tick", html.escape(dataset[:18]), anchor="start"))
        for ci, solver in enumerate(solvers):
            x = padx + ci * cell
            value = grid.get((dataset, solver))
            if value is None:
                body.append(_rect(x, y, cell - 4, 30, 'class="cell-empty"'))
                continue
            alpha = 0.15 + 0.75 * (value / top)
            body.append(_rect(x, y, cell - 4, 30, f'fill="rgba(59,130,246,{alpha:.2f})"'))
            body.append(_text(x + (cell - 4) / 2, y + 20, "cell-lbl", f"{value:.0f}"))
    return _svg("".join(body), width=width, height=height)


def _percentile(ordered: Sequence[float], p: float) -> float:
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    k = (p / 100) * (len(ordered) - 1)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _section(title: str, chart: str, note: str = "") -> str:
    extra = f'<p class="muted">{html.escape(note)}</p>' if note else ""
    return (
        f"<section><h2>{html.escape(title)}</h2>{extra}<div class='chart'>{chart}</div></section>"
    )


def _table(records: Sequence[dict[str, Any]]) -> str:
    rows = []
    for r in reversed(records):
        prov = r.get("provenance", {})
        t, score = _mean(r, "t_total_ms"), _mean(r, "quality_score")
        t_cell = f"{t:.0f}" if t is not None else "—"
        score_cell = f"{score:.1f}" if score is not None else "—"
        hw = f"{prov.get('cpu_cores', '?')} hilos, {prov.get('ram_total_gb', '?')} GB"
        rows.append(
            f"<tr><td>{html.escape(r['dataset'])}</td><td>{html.escape(r['solver'])}</td>"
            f"<td><code>{html.escape(str(prov.get('git_commit', '?')))}</code></td>"
            f"<td>{r.get('reps', '?')}</td><td>{t_cell}</td><td>{score_cell}</td>"
            f"<td>{html.escape(hw)}</td></tr>"
        )
    head = (
        "<tr><th>Dataset</th><th>Solver</th><th>Commit</th><th>Reps</th>"
        "<th>t_total (ms)</th><th>Score</th><th>Hardware</th></tr>"
    )
    return f"<table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>"


def build_dashboard_html(
    records: Sequence[dict[str, Any]], ladder: dict[str, Any] | None = None
) -> str:
    """Construye el HTML completo del dashboard a partir de los registros."""
    if not records:
        body = (
            "<section><p class='muted'>No hay registros en benchmarks/results/. "
            "Ejecuta <code>scripts/bench.py quick</code>.</p></section>"
        )
        return _PAGE.format(body=body)

    sections: list[str] = [f"<section><h2>Corridas registradas</h2>{_table(records)}</section>"]

    # Líneas: t_total por commit, una serie por dataset.
    commits: list[str] = []
    for r in records:
        c = r.get("provenance", {}).get("git_commit", "?")
        if c not in commits:
            commits.append(c)
    by_dataset: dict[str, Sequence[float | None]] = {}
    for dataset in sorted({r["dataset"] for r in records}):
        serie: list[float | None] = []
        for commit in commits:
            match = next(
                (
                    r
                    for r in records
                    if r["dataset"] == dataset
                    and r.get("provenance", {}).get("git_commit") == commit
                ),
                None,
            )
            serie.append(_mean(match, "t_total_ms") if match else None)
        by_dataset[dataset] = serie
    sections.append(
        _section(
            "Tiempo total por versión (commit)",
            _lines(commits, by_dataset, "ms"),
            "Una línea por dataset; el eje X son los commits en orden temporal.",
        )
    )

    # Barras: comparación de solvers (dataset con más solvers).
    solvers_by_dataset: dict[str, dict[str, float]] = {}
    for r in records:
        t = _mean(r, "t_total_ms")
        if t is not None:
            solvers_by_dataset.setdefault(r["dataset"], {})[r["solver"]] = t
    if solvers_by_dataset:
        best = max(solvers_by_dataset, key=lambda d: len(solvers_by_dataset[d]))
        solmap = solvers_by_dataset[best]
        sections.append(
            _section(
                f"Comparación de solvers -- {best}", _bars(list(solmap), list(solmap.values()))
            )
        )

    # Boxplots: dispersión de t_total entre repeticiones (últimos 6 registros).
    recientes = records[-6:]
    box_labels = [f"{r['dataset'][:8]}/{r['solver']}" for r in recientes]
    box_samples = [
        [float(run.get("t_total_ms", 0.0)) for run in r.get("runs", [])] for r in recientes
    ]
    sections.append(
        _section("Dispersión entre repeticiones (boxplot)", _boxplots(box_labels, box_samples))
    )

    # Histograma del registro más reciente.
    ultimo = records[-1]
    hist_vals = [float(run.get("t_total_ms", 0.0)) for run in ultimo.get("runs", [])]
    titulo = f"Histograma de t_total -- {ultimo['dataset']}/{ultimo['solver']}"
    sections.append(_section(titulo, _histogram(hist_vals)))

    # Heatmap dataset x solver.
    datasets = sorted({r["dataset"] for r in records})
    solvers = sorted({r["solver"] for r in records})
    grid = {}
    for r in records:
        t = _mean(r, "t_total_ms")
        if t is not None:
            grid[(r["dataset"], r["solver"])] = t
    sections.append(
        _section("Heatmap tiempo total (dataset x solver)", _heatmap(datasets, solvers, grid))
    )

    # Escalabilidad (si hay ladder.json).
    if ladder and ladder.get("runs"):
        sizes = [str(s) for s in ladder.get("sizes", [])]
        tvals = [float(run.get("t_total_ms", 0.0)) for run in ladder["runs"]]
        exps = ladder.get("exponents", {})
        note = "Exponentes observados: " + ", ".join(f"{k} {v:.2f}" for k, v in exps.items())
        sections.append(_section("Escalabilidad (tiempo vs docentes)", _bars(sizes, tvals), note))

    return _PAGE.format(body="".join(sections))


_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard de Benchmarks -- Motor de Horarios</title>
<style>
:root {{ --bg:#ffffff; --fg:#1f2937; --muted:#6b7280; --card:#f9fafb;
  --border:#e5e7eb; --axis:#9ca3af; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#0f172a; --fg:#e5e7eb; --muted:#94a3b8; --card:#1e293b;
    --border:#334155; --axis:#64748b; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
header {{ padding:24px; border-bottom:1px solid var(--border); }}
header h1 {{ margin:0; font-size:1.4rem; }}
header p {{ margin:4px 0 0; color:var(--muted); }}
main {{ max-width:820px; margin:0 auto; padding:16px; }}
section {{ background:var(--card); border:1px solid var(--border);
  border-radius:10px; padding:16px 20px; margin:16px 0; }}
h2 {{ font-size:1.05rem; margin:0 0 8px; }}
.chart {{ overflow-x:auto; }}
.muted {{ color:var(--muted); font-size:.85rem; margin:4px 0; }}
.axis {{ stroke:var(--axis); stroke-width:1; }}
.tick {{ fill:var(--muted); font-size:11px; }}
.lbl {{ fill:var(--fg); font-size:11px; }}
.cell-lbl {{ fill:var(--fg); font-size:11px; }}
.cell-empty {{ fill:var(--border); }}
.legend {{ margin-top:8px; }}
.key {{ display:inline-flex; align-items:center; gap:5px; margin-right:14px;
  font-size:.8rem; color:var(--muted); }}
.key i {{ width:11px; height:11px; border-radius:2px; display:inline-block; }}
table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--border); }}
th {{ color:var(--muted); font-weight:600; }}
code {{ background:var(--bg); padding:1px 5px; border-radius:4px; }}
</style></head>
<body>
<header><h1>Dashboard de Benchmarks</h1>
<p>Motor de calendarización · generado desde benchmarks/results/ · autocontenido</p></header>
<main>{body}</main>
</body></html>
"""
