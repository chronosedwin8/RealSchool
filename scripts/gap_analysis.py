"""Comparación ampliada Untis vs motor sobre los 4 años reales (Actividad 10).

Para cada año lectivo del Colegio Alemán compara, en TODAS las métricas de la
Actividad 10, el horario real de Untis contra el del motor (reparado con warm
start y pulido en aulas, flujo dos-fases de ADR-018):

    tiempo de generación · calidad · restricciones satisfechas · conflictos ·
    distribución de huecos · balance docente · utilización de aulas

El objetivo no es solo igualar a Untis, sino localizar ventajas medibles. El
resultado se persiste en JSON para el dashboard y las auditorías.

Uso:  .venv\\Scripts\\python.exe scripts\\gap_analysis.py [raíz] [segundos]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from scheduling_platform.core.ids import TimeSlotIndex
from scheduling_platform.core.problem import SchedulingProblem
from scheduling_platform.core.solution import Solution
from scheduling_platform.core.task import Task
from scheduling_platform.engine import MetricsEngine, SchedulingEngine
from scheduling_platform.plugins import registry_with
from scheduling_platform.plugins.catalog.quality import TeacherRoomStabilityPlugin
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.sal.interface import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver
from scheduling_platform.untis import (
    UntisToCanonicalAdapter,
    parse_untis,
    untis_reference_solution,
)

DEFAULT_ROOT = r"C:\pruebasUntis"
_METRICS = MetricsEngine()


def _fix_times(problem: SchedulingProblem, solution: Solution) -> SchedulingProblem:
    """Congela el horario: cada tarea solo puede empezar donde ya está."""
    start_of = {int(a.task_id): int(a.start) for a in solution.assignments}
    tasks = tuple(
        Task(
            task.id,
            task.name,
            task.duration,
            task.requirements,
            allowed_starts=frozenset({TimeSlotIndex(start_of[int(task.id)])})
            if int(task.id) in start_of
            else task.allowed_starts,
            same_segment=task.same_segment,
            attributes=task.attributes,
        )
        for task in problem.tasks
    )
    return SchedulingProblem(grid=problem.grid, resources=problem.resources, tasks=tasks)


def _metrics_of(problem: SchedulingProblem, solution: Solution) -> dict[str, Any]:
    m = _METRICS.compute(problem, solution)
    gaps = _METRICS.gap_distribution(problem, solution, tag="teacher")
    return {
        "room_utilization_pct": round(m.room_utilization_pct, 2),
        "teacher_gaps": m.teacher_gaps,
        "group_gaps": m.group_gaps,
        "teacher_load_balance_pct": round(m.teacher_load_balance_pct, 2),
        "hard_violations": m.hard_violations,
        "quality_score": round(m.quality_score, 2),
        "gap_mean_per_teacher": round(gaps.mean, 2),
        "gap_max_per_teacher": gaps.maximum,
        "gap_variance": round(gaps.variance, 2),
        "gap_histogram": gaps.histogram,
    }


def _run_year(folder: Path, limit: float) -> dict[str, Any] | None:
    xml = folder / "untis.xml"
    if not xml.exists():
        return None

    translation = UntisToCanonicalAdapter().translate(parse_untis(xml))
    problem = translation.problem
    reference, _ = untis_reference_solution(translation)
    config = SolverConfig(max_time_in_seconds=limit, num_search_workers=8, random_seed=1)

    # FASE 1 — reparar (warm start, factibilidad); FASE 2 — pulir aulas.
    t0 = time.perf_counter()
    reparador = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin()]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    reparado = reparador.solve(problem, config, warm_start=reference)
    if not reparado.solved or reparado.solution is None:
        return {"year": folder.name, "solved": False}

    fijo = _fix_times(problem, reparado.solution)
    pulidor = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin(), TeacherRoomStabilityPlugin(weight=1)]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    pulido = pulidor.solve(fijo, config, warm_start=reparado.solution)
    final = pulido if pulido.solved and pulido.solution is not None else reparado
    assert final.solution is not None
    engine_seconds = time.perf_counter() - t0

    result = {
        "year": folder.name,
        "solved": True,
        "classes": len(problem.tasks),
        "untis": {"generation_seconds": None, **_metrics_of(problem, reference)},
        "engine": {
            "generation_seconds": round(engine_seconds, 1),
            **_metrics_of(problem, final.solution),
        },
    }
    _print_year(result)
    return result


def _print_year(r: dict[str, Any]) -> None:
    u, e = r["untis"], r["engine"]
    print(f"\n{'=' * 60}\n  {r['year']} · {r['classes']} clases\n{'=' * 60}")
    print(f"  {'métrica':28s} {'UNTIS':>12s} {'MOTOR':>12s}")
    print(f"  {'-' * 28} {'-' * 12} {'-' * 12}")
    for label, key in (
        ("Utilización de aulas %", "room_utilization_pct"),
        ("Huecos docentes (total)", "teacher_gaps"),
        ("Huecos/docente (media)", "gap_mean_per_teacher"),
        ("Huecos/docente (máx)", "gap_max_per_teacher"),
        ("Varianza de huecos", "gap_variance"),
        ("Balance docente %", "teacher_load_balance_pct"),
        ("Violaciones duras", "hard_violations"),
    ):
        print(f"  {label:28s} {u[key]!s:>12} {e[key]!s:>12}")


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_ROOT)
    limit = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    if not root.exists():
        print(f"No encuentro la carpeta: {root}")
        return 1

    carpetas = (
        [root] if (root / "untis.xml").exists() else sorted(p for p in root.iterdir() if p.is_dir())
    )
    resultados = [out for folder in carpetas if (out := _run_year(folder, limit)) is not None]

    destino = Path("benchmarks") / "gap_analysis.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados en: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
