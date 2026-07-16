"""Gate de regresiones local (Actividades 8 y 11).

Ejecuta la suite rápida (small + medium), compara cada resultado contra su
baseline en benchmarks/baselines/ y **falla** (exit 1) si alguna métrica empeora
más allá de su umbral. Genera benchmarks/regression_report.md.

    regression_gate.py                      # comprueba contra el baseline
    regression_gate.py --update-baseline "motivo justificado"

Los umbrales de tiempo/RAM se validan aquí (local), no en CI, porque en runners
compartidos el ruido dispararía falsos positivos.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scheduling_platform.benchmarks import (
    PRESETS,
    ScenarioSpec,
    Thresholds,
    Violation,
    compare,
    render_report,
    run_scenario,
)
from scheduling_platform.sal.interface import SolverConfig

_GATE_PRESETS = ("small", "medium")
_BASELINES = Path("benchmarks") / "baselines"
_REPORT = Path("benchmarks") / "regression_report.md"


def _measure(preset: str, config: SolverConfig, reps: int) -> dict[str, Any]:
    spec = PRESETS[preset]
    print(f"  · midiendo {spec.name} ({reps} reps)...", flush=True)
    record = run_scenario(ScenarioSpec(dataset=spec, reps=reps, warmup=2), config)
    return record.to_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        metavar="MOTIVO",
        default=None,
        help="acepta las mediciones actuales como nuevo baseline",
    )
    parser.add_argument("--reps", type=int, default=8)
    parser.add_argument("--time", type=float, default=20.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)

    config = SolverConfig(
        max_time_in_seconds=args.time, num_search_workers=args.workers, random_seed=args.seed
    )
    thresholds = Thresholds()
    _BASELINES.mkdir(parents=True, exist_ok=True)

    if args.update_baseline is not None:
        for preset in _GATE_PRESETS:
            doc = _measure(preset, config, args.reps)
            doc["justification"] = args.update_baseline
            (_BASELINES / f"{preset}.json").write_text(
                json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        print(f"\nBaseline actualizado ({args.update_baseline}).")
        return 0

    results: list[tuple[str, list[Violation]]] = []
    missing = False
    for preset in _GATE_PRESETS:
        baseline_path = _BASELINES / f"{preset}.json"
        candidate = _measure(preset, config, args.reps)
        if not baseline_path.exists():
            print(f"  ! sin baseline para {preset}: usa --update-baseline primero")
            missing = True
            continue
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        results.append((candidate["dataset"], compare(baseline, candidate, thresholds)))

    report = render_report(results)
    _REPORT.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Informe: {_REPORT}")

    if missing:
        return 2
    total = sum(len(v) for _, v in results)
    return 1 if total > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
