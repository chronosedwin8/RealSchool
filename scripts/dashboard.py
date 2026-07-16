"""Genera el dashboard HTML estático desde los registros de benchmarking.

    .venv\\Scripts\\python.exe scripts\\dashboard.py [results_dir] [salida.html]

Lee benchmarks/results/*.json (y ladder.json si existe) y escribe un HTML
autocontenido en benchmarks/dashboard.html.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scheduling_platform.benchmarks import DEFAULT_RESULTS_DIR
from scheduling_platform.benchmarks.dashboard import build_dashboard_html, load_records


def main() -> int:
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RESULTS_DIR
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("benchmarks") / "dashboard.html"

    records = load_records(results_dir)
    ladder_path = results_dir / "ladder.json"
    ladder = None
    if ladder_path.exists():
        try:
            ladder = json.loads(ladder_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            ladder = None

    html_text = build_dashboard_html(records, ladder)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text, encoding="utf-8")
    print(f"Dashboard generado: {out} ({len(records)} registros)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
