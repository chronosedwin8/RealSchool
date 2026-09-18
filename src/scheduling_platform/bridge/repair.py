"""Reparar: CP-SAT con cambio mínimo sobre una ventana del horario (estrategia "Reparar").

CP-SAT deja de ser el generador y pasa a ser el **reparador** (sección 7 del
documento maestro): resuelve choques y coloca sesiones sueltas moviendo lo menos
posible, partiendo del horario actual.

En lugar de congelar las 1.676 sesiones con variables booleanas (el enfoque de
`ReOptimizationEngine`), se construye un **subproblema** exacto y pequeño:

- las tareas de la *ventana* (las implicadas en choques y las no colocadas),
  libres, con su dominio completo;
- una tarea *bloqueadora* fija por cada asignación congelada que comparte algún
  recurso con la ventana, que ocupa exactamente esos recursos a su hora.

El objetivo penaliza mover una sesión de su celda original (cambio mínimo). Si la
ventana no tiene solución, se amplía con las sesiones vecinas (mismo profesor o
clase, mismo día) y se reintenta.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from scheduling_platform.core import (
    ResourceRequirement,
    SchedulingProblem,
    Solution,
    Task,
    TaskId,
)
from scheduling_platform.engine import SchedulingEngine
from scheduling_platform.plugins import registry_with
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.sal.interface import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver
from scheduling_platform.untis_model import Timetable, UntisProject

from .plugins import MinimalChangePlugin
from .rebuild import solution_to_timetable, timetable_to_solution
from .translate import SessionRef, Translation, UntisTranslator

#: Peso de mover una sesión de su celda original.
MOVE_WEIGHT = 10
#: Peso de cambiarle el aula a una sesión (menos grave que moverla de hora).
ROOM_CHANGE_WEIGHT = 3


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    """Resultado de una reparación."""

    timetable: Timetable
    status: str
    """`repaired`, `partial`, `nothing_to_do`, `infeasible` o `cancelled`."""
    moved: tuple[SessionRef, ...] = field(default_factory=tuple)
    """Sesiones que cambiaron de hora."""
    rerouted: tuple[SessionRef, ...] = field(default_factory=tuple)
    """Sesiones que conservaron la hora pero cambiaron de aula."""
    placed: tuple[SessionRef, ...] = field(default_factory=tuple)
    remaining_conflicts: int = 0
    remaining_unplaced: int = 0
    rounds: int = 0
    elapsed: float = 0.0
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("repaired", "nothing_to_do")


# --------------------------------------------------------------------------- #
# Conflictos sobre la solución canónica
# --------------------------------------------------------------------------- #


def conflicting_tasks(problem: SchedulingProblem, solution: Solution) -> set[int]:
    """Tareas que comparten un recurso a la vez con otra (misma semántica que el juez)."""
    duracion = {int(t.id): t.duration for t in problem.tasks}
    por_recurso: defaultdict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for a in solution.assignments:
        tid = int(a.task_id)
        inicio = int(a.start)
        for r in a.resource_ids:
            por_recurso[int(r)].append((inicio, inicio + duracion[tid], tid))
    capacidad = {int(r.id): r.capacity for r in problem.resources}
    implicadas: set[int] = set()
    for rid, intervalos in por_recurso.items():
        if capacidad.get(rid, 1) > 1:
            continue
        intervalos.sort()
        for i, (_s1, e1, t1) in enumerate(intervalos):
            for s2, _e2, t2 in intervalos[i + 1 :]:
                if s2 >= e1:
                    break
                implicadas.update((t1, t2))
    return implicadas


def _neighbours(
    problem: SchedulingProblem, solution: Solution, window: set[int], clock_len: int
) -> set[int]:
    """Tareas colocadas que comparten profesor o clase con la ventana el mismo día."""
    fijos = {int(a.task_id): {int(r) for r in a.resource_ids} for a in solution.assignments}
    dia = {int(a.task_id): int(a.start) // clock_len for a in solution.assignments}
    recursos_ventana = set().union(*(fijos.get(t, set()) for t in window)) if window else set()
    dias_ventana = {dia[t] for t in window if t in dia}
    return {
        t
        for t, rs in fijos.items()
        if t not in window and dia[t] in dias_ventana and rs & recursos_ventana
    }


# --------------------------------------------------------------------------- #
# Subproblema de la ventana
# --------------------------------------------------------------------------- #


def _subproblem(
    problem: SchedulingProblem, baseline: Solution, window: set[int]
) -> tuple[SchedulingProblem, dict[int, int]]:
    """Tareas de la ventana + bloqueadoras fijas de lo congelado que les afecta.

    Devuelve el subproblema y `bloqueadora -> tarea congelada` (para depurar).
    """
    tareas = {int(t.id): t for t in problem.tasks}
    etiquetas_recurso = {int(r.id): r.tags for r in problem.resources}

    # Recursos que la ventana podría usar: los que llevan alguna etiqueta requerida.
    requeridas = {req.tag for t in window for req in tareas[t].requirements}
    posibles = {rid for rid, tags in etiquetas_recurso.items() if tags & requeridas}

    siguiente = max(tareas) + 1
    bloqueadoras: list[Task] = []
    origen: dict[int, int] = {}
    for a in baseline.assignments:
        tid = int(a.task_id)
        if tid in window:
            continue
        afectados = [int(r) for r in a.resource_ids if int(r) in posibles]
        if not afectados:
            continue
        # Cada recurso afectado se fija por su etiqueta única (`teacher#X`, `group#Y`, `room#Z`).
        reqs = []
        for rid in afectados:
            unica = next(
                (
                    t
                    for t in sorted(etiquetas_recurso[rid])
                    if "#" in t and not t.startswith(("roompool#", "teacherpool#"))
                ),
                None,
            )
            if unica is not None:
                reqs.append(ResourceRequirement(unica))
        if not reqs:
            continue
        original = tareas[tid]
        bloqueadoras.append(
            Task(
                TaskId(siguiente),
                f"(fijo) {original.name}",
                original.duration,
                tuple(reqs),
                allowed_starts=frozenset({a.start}),
                same_segment=original.same_segment,
            )
        )
        origen[siguiente] = tid
        siguiente += 1

    sub = replace(
        problem,
        tasks=(*(tareas[t] for t in sorted(window)), *bloqueadoras),
    )
    return sub, origen


def _solve_window(
    tr: Translation,
    baseline: Solution,
    window: set[int],
    *,
    time_limit: float,
    seed: int,
    should_stop: Callable[[], bool] | None,
) -> Solution | None:
    sub, origen = _subproblem(tr.problem, baseline, window)
    previos = {int(a.task_id): int(a.start) for a in baseline.assignments}
    original = tuple((t, previos[t]) for t in sorted(window) if t in previos)
    salas = {int(r.id) for r in tr.problem.resources if "room" in r.tags}
    aulas = tuple(
        (int(a.task_id), int(r))
        for a in baseline.assignments
        if int(a.task_id) in window
        for r in a.resource_ids
        if int(r) in salas
    )
    registro = registry_with(
        [
            IntervalNoOverlapPlugin(),
            MinimalChangePlugin(
                original=original,
                rooms=aulas,
                weight=MOVE_WEIGHT,
                room_weight=ROOM_CHANGE_WEIGHT,
            ),
        ]
    )
    motor = SchedulingEngine(registry=registro, solver_factory=ORToolsSolver)
    config = SolverConfig(
        max_time_in_seconds=time_limit,
        num_search_workers=8,
        random_seed=seed,
        should_stop=should_stop,
    )
    resultado = motor.solve(sub, config)
    if not resultado.solved or resultado.solution is None:
        return None
    nuevas = {
        int(a.task_id): a for a in resultado.solution.assignments if int(a.task_id) not in origen
    }
    fusion = [a for a in baseline.assignments if int(a.task_id) not in window]
    fusion += [nuevas[t] for t in sorted(window) if t in nuevas]
    return Solution(assignments=tuple(fusion), objective_value=0)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


def repair(
    project: UntisProject,
    timetable: Timetable,
    *,
    time_limit: float = 30.0,
    seed: int = 0,
    max_rounds: int = 3,
    include_unplaced: bool = True,
    optimize_teachers: bool = False,
    should_stop: Callable[[], bool] | None = None,
    timetable_id: str | None = None,
) -> RepairOutcome:
    """Repara `timetable`: sin choques y con lo no colocado dentro, moviendo lo mínimo."""
    t0 = time.perf_counter()
    tr = _translate_with_reference(project, timetable, optimize_teachers)
    rb = timetable_to_solution(tr, timetable)
    base = rb.solution
    ventana = conflicting_tasks(tr.problem, base)
    sin_colocar = {tr.task_of[ref] for ref in rb.unplaced} if include_unplaced else set()
    ventana |= sin_colocar
    destino = timetable_id or timetable.id

    if not ventana:
        return RepairOutcome(
            timetable,
            "nothing_to_do",
            elapsed=time.perf_counter() - t0,
            message="El horario no tiene choques ni sesiones sin colocar.",
        )

    reparado: Solution | None = None
    rondas = 0
    presupuesto = time_limit
    while rondas < max_rounds and presupuesto > 0:
        if should_stop is not None and should_stop():
            break
        rondas += 1
        inicio = time.perf_counter()
        reparado = _solve_window(
            tr, base, ventana, time_limit=presupuesto, seed=seed, should_stop=should_stop
        )
        presupuesto -= time.perf_counter() - inicio
        if reparado is not None:
            break
        ventana |= _neighbours(tr.problem, base, ventana, tr.clock.day_length)

    elapsed = time.perf_counter() - t0
    if reparado is None:
        cancelado = should_stop is not None and should_stop()
        return RepairOutcome(
            timetable,
            "cancelled" if cancelado else "infeasible",
            rounds=rondas,
            elapsed=elapsed,
            remaining_conflicts=len(conflicting_tasks(tr.problem, base)),
            remaining_unplaced=len(rb.unplaced),
            message="No se encontró una reparación en el tiempo dado."
            if not cancelado
            else "Reparación detenida.",
        )

    antes = {int(a.task_id): int(a.start) for a in base.assignments}
    despues = {int(a.task_id): int(a.start) for a in reparado.assignments}
    movidas = tuple(
        tr.session_of[t] for t in sorted(antes) if t in despues and despues[t] != antes[t]
    )
    recursos_antes = {int(a.task_id): set(a.resource_ids) for a in base.assignments}
    reasignadas = tuple(
        tr.session_of[int(a.task_id)]
        for a in reparado.assignments
        if int(a.task_id) in antes
        and despues[int(a.task_id)] == antes[int(a.task_id)]
        and set(a.resource_ids) != recursos_antes[int(a.task_id)]
    )
    colocadas = tuple(tr.session_of[t] for t in sorted(despues) if t not in antes)
    restantes = len(conflicting_tasks(tr.problem, reparado))
    nuevo = solution_to_timetable(
        tr, reparado, timetable_id=destino, name=timetable.name, reference=timetable
    )
    # Las obligaciones no lectivas no se traducen: se conservan tal cual.
    traducidas = {r.lesson for r in tr.task_of}
    conservadas = tuple(a for a in timetable.assignments if a.lesson_number not in traducidas)
    nuevo = replace(
        nuevo,
        assignments=tuple(
            sorted(
                (*nuevo.assignments, *conservadas),
                key=lambda x: (x.lesson_number, x.day, x.period, x.line),
            )
        ),
    )
    sin = len(tr.task_of) - len(despues)
    estado = "repaired" if restantes == 0 and sin == 0 else "partial"
    return RepairOutcome(
        nuevo,
        estado,
        moved=movidas,
        rerouted=reasignadas,
        placed=colocadas,
        remaining_conflicts=restantes,
        remaining_unplaced=sin,
        rounds=rondas,
        elapsed=elapsed,
        message=(
            f"{len(movidas)} sesión(es) movida(s), {len(reasignadas)} con otra aula, "
            f"{len(colocadas)} colocada(s)."
        ),
    )


def _translate_with_reference(
    project: UntisProject, timetable: Timetable, optimize_teachers: bool
) -> Translation:
    """Traduce usando `timetable` como referencia de duraciones y aulas."""
    proyecto = (
        project
        if project.timetable_by_id(timetable.id) is not None
        else (project.with_timetable(timetable))
    )
    return UntisTranslator(optimize_teachers=optimize_teachers, reference=timetable.id).translate(
        proyecto
    )


__all__ = [
    "MOVE_WEIGHT",
    "ROOM_CHANGE_WEIGHT",
    "MinimalChangePlugin",
    "RepairOutcome",
    "conflicting_tasks",
    "repair",
]
