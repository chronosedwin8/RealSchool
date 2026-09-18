"""Pulido CP-SAT por ventanas (fase 3 del documento maestro).

Toma un horario ya bueno (de la heurística o de Untis) y lo mejora ventana a
ventana. Cada ventana es la semana entera de **una clase**: todas sus sesiones
quedan libres y el resto del colegio queda congelado como tareas bloqueadoras
(ver `repair._subproblem`). CP-SAT minimiza, en períodos y exactamente como el
evaluador de referencia:

- los huecos de la clase y los de cada profesor que la atiende (sus sesiones
  en otras clases cuentan como ocupación fija);
- los períodos dobles pedidos por sus lecciones;
- un cambio mínimo, con peso bajo, para no remover sin motivo.

El juez es siempre el evaluador de referencia: una ventana solo se acepta si el
número de evaluación **completo** del horario baja. Así CP-SAT puede trabajar
con una visión local sin riesgo de empeorar el conjunto.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from scheduling_platform.core import Solution
from scheduling_platform.engine import SchedulingEngine
from scheduling_platform.plugins import SchedulingPlugin, registry_with
from scheduling_platform.sal.interface import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver
from scheduling_platform.untis_model import (
    Evaluation,
    Timetable,
    UntisProject,
    Weighting,
)
from scheduling_platform.untis_model.evaluation import Evaluator

from .rebuild import solution_to_timetable, timetable_to_solution
from .repair import _subproblem
from .translate import SessionRef, Translation, UntisTranslator
from .weighting import Geometry, window_plugins


@dataclass(frozen=True, slots=True)
class PolishOutcome:
    """Resultado del pulido."""

    timetable: Timetable
    before: Evaluation
    after: Evaluation
    windows_tried: int = 0
    windows_accepted: int = 0
    elapsed: float = 0.0
    log: tuple[str, ...] = field(default_factory=tuple)

    @property
    def improved(self) -> bool:
        return self.after.total < self.before.total


# --------------------------------------------------------------------------- #
# Ventanas
# --------------------------------------------------------------------------- #


def _class_windows(tr: Translation, ev: Evaluator, timetable: Timetable) -> Iterator[str]:
    """Clases ordenadas por lo que aportan a la evaluación (peor primero)."""
    informe = ev.report(timetable)
    peso: defaultdict[str, int] = defaultdict(int)
    for v in informe.violations:
        if v.entity_id and v.entity_id in ev.class_grid:
            peso[v.entity_id] += v.amount
    clases = [c.id for c in tr.project.classes if c.id in ev.class_grid]
    yield from sorted(clases, key=lambda c: (-peso.get(c, 0), c))


def _solve(
    tr: Translation,
    base: Solution,
    window: set[int],
    plugins: list[SchedulingPlugin],
    *,
    time_limit: float,
    seed: int,
    should_stop: Callable[[], bool] | None,
) -> Solution | None:
    sub, origen = _subproblem(tr.problem, base, window)
    motor = SchedulingEngine(registry=registry_with(plugins), solver_factory=ORToolsSolver)
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
    fusion = [a for a in base.assignments if int(a.task_id) not in window]
    fusion += [nuevas[t] for t in sorted(window) if t in nuevas]
    return Solution(assignments=tuple(fusion), objective_value=0)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


def polish(
    project: UntisProject,
    timetable: Timetable,
    *,
    weighting: Weighting | None = None,
    time_limit: float = 60.0,
    window_time: float = 5.0,
    max_windows: int | None = None,
    seed: int = 0,
    should_stop: Callable[[], bool] | None = None,
    on_window: Callable[[str, int, bool], None] | None = None,
) -> PolishOutcome:
    """Pule `timetable` clase a clase con CP-SAT; nunca devuelve algo peor."""
    t0 = time.perf_counter()
    w = weighting if weighting is not None else project.weighting
    proyecto = (
        project if project.timetable_by_id(timetable.id) else project.with_timetable(timetable)
    )
    tr = UntisTranslator(reference=timetable.id).translate(proyecto)
    ev = Evaluator(project)
    geo = Geometry.of(tr)

    mejor = timetable
    antes = ev.evaluate(mejor, w)
    mejor_e = antes
    base = timetable_to_solution(tr, mejor).solution
    colocadas = {int(a.task_id) for a in base.assignments}
    probadas = aceptadas = 0
    registro: list[str] = []

    for clase in _class_windows(tr, ev, timetable):
        if should_stop is not None and should_stop():
            break
        restante = time_limit - (time.perf_counter() - t0)
        if restante <= 0.5 or (max_windows is not None and probadas >= max_windows):
            break
        ventana = {
            tid
            for ref, tid in tr.task_of.items()
            if tid in colocadas and clase in tr.project.lesson_by_number[ref.lesson].classes
        }
        if len(ventana) < 2:
            continue
        probadas += 1
        plugins = window_plugins(tr, geo, ev, base, ventana, clase, w)
        nueva = _solve(
            tr,
            base,
            ventana,
            plugins,
            time_limit=min(window_time, restante),
            seed=seed,
            should_stop=should_stop,
        )
        aceptada = False
        if nueva is not None:
            candidato = _merge_duties(
                solution_to_timetable(
                    tr, nueva, timetable_id=timetable.id, name=timetable.name, reference=mejor
                ),
                mejor,
                tr,
            )
            e = ev.evaluate(candidato, w)
            if e.total < mejor_e.total:
                registro.append(f"{clase}: {mejor_e.total} -> {e.total}")
                mejor, mejor_e, base = candidato, e, nueva
                aceptadas += 1
                aceptada = True
        if on_window is not None:
            on_window(clase, mejor_e.total, aceptada)

    return PolishOutcome(
        mejor,
        antes,
        mejor_e,
        windows_tried=probadas,
        windows_accepted=aceptadas,
        elapsed=time.perf_counter() - t0,
        log=tuple(registro),
    )


def _merge_duties(nuevo: Timetable, previo: Timetable, tr: Translation) -> Timetable:
    """Las lecciones no traducidas (obligaciones) se conservan tal cual."""
    traducidas = {r.lesson for r in tr.task_of}
    conservadas = tuple(a for a in previo.assignments if a.lesson_number not in traducidas)
    return Timetable(
        id=nuevo.id,
        name=nuevo.name,
        assignments=tuple(
            sorted(
                (*nuevo.assignments, *conservadas),
                key=lambda x: (x.lesson_number, x.day, x.period, x.line),
            )
        ),
    )


__all__ = ["PolishOutcome", "SessionRef", "polish"]
