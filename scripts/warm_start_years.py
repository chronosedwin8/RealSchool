"""Warm start con horarios reales de Untis de varios años.

Para cada año lectivo exportado de Untis:
1. Traduce el export al Modelo Canónico y reconstruye el horario de Untis.
2. Resuelve **en frío** (desde cero) con un límite de tiempo.
3. Resuelve **sembrado** con el horario de Untis (warm start) e igual límite.
4. Compara: ¿el warm start encuentra un horario válido donde el frío no?
   ¿cuántas sesiones conserva del horario original?

Uso:
    .venv\\Scripts\\python.exe scripts\\warm_start_years.py [ruta_carpetas] [segundos]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from scheduling_platform.core.solution import Solution
from scheduling_platform.engine import EngineResult, MetricsEngine, SchedulingEngine
from scheduling_platform.plugins import registry_with
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.sal.interface import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver
from scheduling_platform.untis import (
    UntisToCanonicalAdapter,
    parse_untis,
    untis_reference_solution,
)

DEFAULT_ROOT = r"C:\pruebasUntis"


def _engine() -> SchedulingEngine:
    return SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin()]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )


def _kept(reference: Solution, result: EngineResult) -> int:
    """Cuántas sesiones conservan el mismo inicio que en el horario de Untis."""
    if result.solution is None:
        return 0
    base = {int(a.task_id): int(a.start) for a in reference.assignments}
    return sum(1 for a in result.solution.assignments if base.get(int(a.task_id)) == int(a.start))


def _run_year(folder: Path, limit: float) -> dict[str, object] | None:
    xml = folder / "untis.xml"
    if not xml.exists():
        return None

    export = parse_untis(xml)
    translation = UntisToCanonicalAdapter().translate(export)
    problem = translation.problem
    reference, _ = untis_reference_solution(translation)
    metrics = MetricsEngine()

    config = SolverConfig(max_time_in_seconds=limit, num_search_workers=8, random_seed=1)

    t0 = time.perf_counter()
    frio = _engine().solve(problem, config)
    t_frio = time.perf_counter() - t0

    t0 = time.perf_counter()
    caliente = _engine().solve(problem, config, warm_start=reference)
    t_caliente = time.perf_counter() - t0

    m_frio = metrics.compute(problem, frio.solution) if frio.solution else None
    m_cal = metrics.compute(problem, caliente.solution) if caliente.solution else None

    print(f"\n{'=' * 66}")
    print(f"  {folder.name}  ·  {len(problem.tasks)} clases · {len(problem.resources)} recursos")
    print(f"{'=' * 66}")
    print(f"  {'':22s} {'EN FRÍO':>16s} {'SEMBRADO (warm)':>18s}")
    print(f"  {'-' * 22} {'-' * 16} {'-' * 18}")
    print(
        f"  {'Estado':22s} "
        f"{(frio.status.value if frio.status else 'pre-solver'):>16s} "
        f"{(caliente.status.value if caliente.status else 'pre-solver'):>18s}"
    )
    print(
        f"  {'Horario válido':22s} "
        f"{('SÍ' if frio.solved else 'no'):>16s} "
        f"{('SÍ' if caliente.solved else 'no'):>18s}"
    )
    print(
        f"  {'Calidad (0-100)':22s} "
        f"{(f'{m_frio.quality_score:.1f}' if m_frio else '-'):>16s} "
        f"{(f'{m_cal.quality_score:.1f}' if m_cal else '-'):>18s}"
    )
    print(
        f"  {'Violaciones duras':22s} "
        f"{(str(m_frio.hard_violations) if m_frio else '-'):>16s} "
        f"{(str(m_cal.hard_violations) if m_cal else '-'):>18s}"
    )
    total = len(reference.assignments)
    print(
        f"  {'Sesiones == Untis':22s} "
        f"{f'{_kept(reference, frio)}/{total}':>16s} "
        f"{f'{_kept(reference, caliente)}/{total}':>18s}"
    )
    print(f"  {'Tiempo total':22s} {f'{t_frio:.0f}s':>16s} {f'{t_caliente:.0f}s':>18s}")

    return {
        "year": folder.name,
        "tasks": len(problem.tasks),
        "cold": {
            "status": frio.status.value if frio.status else None,
            "solved": frio.solved,
            "quality": round(m_frio.quality_score, 1) if m_frio else None,
            "kept_from_untis": _kept(reference, frio),
            "seconds": round(t_frio, 1),
        },
        "warm": {
            "status": caliente.status.value if caliente.status else None,
            "solved": caliente.solved,
            "quality": round(m_cal.quality_score, 1) if m_cal else None,
            "kept_from_untis": _kept(reference, caliente),
            "seconds": round(t_caliente, 1),
        },
        "untis_sessions": total,
    }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_ROOT)
    limit = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0
    if not root.exists():
        print(f"No encuentro la carpeta: {root}")
        return 1

    print(f"Warm start con horarios reales de Untis · límite {limit:.0f}s por resolución")
    resultados = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        out = _run_year(folder, limit)
        if out is not None:
            resultados.append(out)

    destino = Path("benchmarks") / "warm_start_years.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados en: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
