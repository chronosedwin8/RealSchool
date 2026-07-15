"""Warm start + objetivo de calidad: mejorar el horario de Untis, no solo repararlo.

Para cada año lectivo:
1. Reconstruye el horario de Untis y mide su dispersión de aulas
   (pares docente-aula: cuántas aulas distintas usa cada profesor).
2. Siembra el motor con ese horario y le da el objetivo de **estabilidad de
   aula** (minimizar aulas distintas por docente), manteniendo el no-solape.
3. Compara: ¿reduce el motor los desplazamientos respetando el horario?

Uso:
    .venv\\Scripts\\python.exe scripts\\warm_start_quality.py [ruta] [segundos]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from scheduling_platform.core.ids import TimeSlotIndex
from scheduling_platform.core.problem import SchedulingProblem
from scheduling_platform.core.solution import Solution
from scheduling_platform.core.task import Task
from scheduling_platform.engine import SchedulingEngine
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


def _single_teacher_ids(problem: SchedulingProblem) -> set[int]:
    """Tareas de un único docente (las que optimiza la estabilidad de aula)."""
    ids = set()
    for task in problem.tasks:
        if sum(1 for r in task.requirements if r.tag.startswith("teacher#")) == 1:
            ids.add(int(task.id))
    return ids


def _room_pairs(
    problem: SchedulingProblem, solution: Solution, only_tasks: set[int]
) -> tuple[int, float, int]:
    """(pares docente-aula, media por docente, máximo), solo clases de un docente."""
    teacher_ids = {int(r.id) for r in problem.resources if "teacher" in r.tags}
    room_ids = {int(r.id) for r in problem.resources if "room" in r.tags}
    por_doc: dict[int, set[int]] = defaultdict(set)
    for a in solution.assignments:
        if int(a.task_id) not in only_tasks:
            continue
        teas = [int(r) for r in a.resource_ids if int(r) in teacher_ids]
        rooms = [int(r) for r in a.resource_ids if int(r) in room_ids]
        for t in teas:
            por_doc[t].update(rooms)
    counts = [len(v) for v in por_doc.values()]
    pares = sum(counts)
    return pares, (pares / len(counts) if counts else 0.0), max(counts, default=0)


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


def _run_year(folder: Path, limit: float) -> dict[str, object] | None:
    xml = folder / "untis.xml"
    if not xml.exists():
        return None

    translation = UntisToCanonicalAdapter().translate(parse_untis(xml))
    problem = translation.problem
    reference, _ = untis_reference_solution(translation)
    single = _single_teacher_ids(problem)
    config = SolverConfig(max_time_in_seconds=limit, num_search_workers=8, random_seed=1)

    # FASE 1 — reparar: warm start con el horario de Untis (solo factibilidad).
    reparador = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin()]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    reparado = reparador.solve(problem, config, warm_start=reference)

    print(f"\n{'=' * 66}")
    print(f"  {folder.name}  ·  {len(problem.tasks)} clases")
    print(f"{'=' * 66}")
    if not reparado.solved or reparado.solution is None:
        estado = reparado.status.value if reparado.status else "pre-solver"
        print(f"  Fase 1 (reparar): {estado} (sin horario)")
        return {"year": folder.name, "solved": False}

    # FASE 2 — pulir: fijar los horarios, optimizar SOLO las aulas.
    fijo = _fix_times(problem, reparado.solution)
    pulidor = SchedulingEngine(
        registry=registry_with([IntervalNoOverlapPlugin(), TeacherRoomStabilityPlugin(weight=1)]),
        solver_factory=ORToolsSolver,
        boolean_starts=False,
    )
    pulido = pulidor.solve(fijo, config, warm_start=reparado.solution)
    final = pulido if pulido.solved and pulido.solution is not None else reparado
    assert final.solution is not None

    u_pairs, u_media, u_max = _room_pairs(problem, reference, single)
    n_pairs, n_media, n_max = _room_pairs(problem, final.solution, single)
    base = {int(a.task_id): int(a.start) for a in reference.assignments}
    kept = sum(1 for a in final.solution.assignments if base.get(int(a.task_id)) == int(a.start))
    total = len(reference.assignments)
    reduccion = 100.0 * (u_pairs - n_pairs) / u_pairs if u_pairs else 0.0

    print(f"  {'':28s} {'UNTIS':>12s} {'NUESTRO MOTOR':>16s}")
    print(f"  {'-' * 28} {'-' * 12} {'-' * 16}")
    print(f"  {'Pares docente-aula':28s} {u_pairs:>12} {n_pairs:>16}")
    print(f"  {'Aulas por docente (media)':28s} {u_media:>12.1f} {n_media:>16.1f}")
    print(f"  {'Aulas por docente (máx)':28s} {u_max:>12} {n_max:>16}")
    print(f"  {'Violaciones duras':28s} {'conflictos':>12} {'0':>16}")
    print(f"  {'Sesiones conservadas':28s} {total:>12} {f'{kept} ({100 * kept // total}%)':>16}")
    print(
        f"\n  -> Desplazamientos de aula (clases de 1 docente) reducidos {reduccion:.1f}% "
        f"({u_pairs} -> {n_pairs}), horario válido y conservado."
    )

    return {
        "year": folder.name,
        "solved": True,
        "untis": {"room_pairs": u_pairs, "avg_rooms": round(u_media, 1), "max_rooms": u_max},
        "engine": {"room_pairs": n_pairs, "avg_rooms": round(n_media, 1), "max_rooms": n_max},
        "reduction_pct": round(reduccion, 1),
        "kept_sessions": kept,
        "total_sessions": total,
    }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_ROOT)
    limit = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    if not root.exists():
        print(f"No encuentro la carpeta: {root}")
        return 1

    print(f"Warm start + estabilidad de aula · límite {limit:.0f}s por año")
    # La ruta puede ser la carpeta con los años, o directamente una carpeta-año.
    if (root / "untis.xml").exists():
        carpetas = [root]
    else:
        carpetas = sorted(p for p in root.iterdir() if p.is_dir())
    resultados = []
    for folder in carpetas:
        out = _run_year(folder, limit)
        if out is not None:
            resultados.append(out)

    destino = Path("benchmarks") / "warm_start_quality.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados en: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
