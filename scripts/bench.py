"""CLI única de benchmarking (Actividades 4, 5, 8).

    bench run <preset> [--reps N] [--time S] [--workers N] [--seed N]
    bench quick                 # suite rápida (gate): small + medium
    bench full                  # suite completa: todos los presets, más repeticiones
    bench compare <A.json> <B.json>

Cada corrida se registra automáticamente en benchmarks/results/ (JSON + Markdown).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scheduling_platform.benchmarks import (
    DEFAULT_REPS,
    DEFAULT_RESULTS_DIR,
    PRESETS,
    BenchmarkRecord,
    ScenarioSpec,
    run_scenario,
)
from scheduling_platform.sal.interface import SolverConfig

_QUICK = ("small", "medium")
_FULL = ("small", "medium", "large", "xl")


def _config(args: argparse.Namespace) -> SolverConfig:
    return SolverConfig(
        max_time_in_seconds=args.time,
        num_search_workers=args.workers,
        random_seed=args.seed,
    )


def _run_preset(preset: str, reps: int, config: SolverConfig, out: Path) -> BenchmarkRecord:
    spec = PRESETS[preset]
    scenario = ScenarioSpec(dataset=spec, reps=reps, warmup=2)
    print(f"  · {spec.name}: {reps} repeticiones (+2 calentamiento)...", flush=True)
    record = run_scenario(scenario, config)
    path = record.save(out)
    t = record.aggregates.get("t_total_ms", {})
    if t:
        print(f"    t_total: {t['mean']:.0f} ms (IC95 [{t['ci95_low']:.0f}, {t['ci95_high']:.0f}])")
    print(f"    -> {path}")
    return record


def _cmd_run(args: argparse.Namespace) -> int:
    if args.preset not in PRESETS:
        print(f"preset desconocido: {args.preset} (opciones: {', '.join(PRESETS)})")
        return 1
    reps = args.reps if args.reps is not None else DEFAULT_REPS.get(args.preset, 5)
    _run_preset(args.preset, reps, _config(args), Path(args.out))
    return 0


def _cmd_suite(presets: tuple[str, ...], args: argparse.Namespace) -> int:
    config = _config(args)
    out = Path(args.out)
    for preset in presets:
        reps = args.reps if args.reps is not None else DEFAULT_REPS.get(preset, 5)
        _run_preset(preset, reps, config, out)
    print(f"\nRegistros en: {out}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    a = BenchmarkRecord.from_dict(json.loads(Path(args.a).read_text(encoding="utf-8")))
    b = BenchmarkRecord.from_dict(json.loads(Path(args.b).read_text(encoding="utf-8")))
    print(
        f"Comparación: {a.dataset}/{a.solver} ({a.provenance.git_commit}) "
        f"vs {b.dataset}/{b.solver} ({b.provenance.git_commit})\n"
    )
    metrics = ("t_total_ms", "t_solve_ms", "ram_peak_mb", "num_variables", "quality_score")
    print(f"{'Métrica':<18} {'A (media)':>14} {'B (media)':>14} {'Δ%':>10}")
    print("-" * 58)
    for m in metrics:
        ma = a.aggregates.get(m, {}).get("mean")
        mb = b.aggregates.get(m, {}).get("mean")
        if ma is None or mb is None:
            continue
        delta = 100.0 * (mb - ma) / ma if ma else 0.0
        print(f"{m:<18} {ma:>14.2f} {mb:>14.2f} {delta:>+9.1f}%")
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--reps", type=int, default=None, help="repeticiones (escalonadas)")
    common.add_argument("--time", type=float, default=30.0, help="límite de solver (s)")
    common.add_argument("--workers", type=int, default=8, help="hilos de búsqueda")
    common.add_argument("--seed", type=int, default=1, help="semilla del solver")
    common.add_argument("--out", default=str(DEFAULT_RESULTS_DIR), help="carpeta de resultados")

    parser = argparse.ArgumentParser(prog="bench", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", parents=[common], help="mide un preset")
    p_run.add_argument("preset", help=f"uno de: {', '.join(PRESETS)}")
    sub.add_parser("quick", parents=[common], help="suite rápida (gate): small + medium")
    sub.add_parser("full", parents=[common], help="suite completa: todos los presets")
    p_cmp = sub.add_parser("compare", help="compara dos registros JSON")
    p_cmp.add_argument("a")
    p_cmp.add_argument("b")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return _cmd_run(args)
    if args.cmd == "quick":
        return _cmd_suite(_QUICK, args)
    if args.cmd == "full":
        return _cmd_suite(_FULL, args)
    if args.cmd == "compare":
        return _cmd_compare(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
