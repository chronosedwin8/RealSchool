"""Orquestador de estrategias: heurística (fases 1-2) + CP-SAT (fase 3).

`heuristic` no puede importar el motor (ADR-034), así que la combinación de las
tres fases del documento maestro (sección 7) se hace aquí:

| Estrategia | Heurística                     | CP-SAT (fase 3)                           |
|------------|--------------------------------|-------------------------------------------|
| A          | colocación + mejora corta       | no                                        |
| B, D, E    | colocación + mejora larga       | repara choques y coloca lo que quedó suelto |
| Reparar    | pulido corto tras reparar       | primero: cambio mínimo sobre el horario actual |

El juez de todo es el evaluador de referencia (`untis_model.evaluation`): cada
resultado lleva su número de evaluación y nunca se devuelve un horario peor que
el de partida cuando se repara.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from scheduling_platform.heuristic import HeuristicResult, Progress, Strategy
from scheduling_platform.heuristic import optimize as heuristic_optimize
from scheduling_platform.untis_model import Evaluation, Timetable, UntisProject, Weighting
from scheduling_platform.untis_model.evaluation import Evaluator

from .repair import RepairOutcome, repair

#: Tiempo que se reserva a CP-SAT en B/D/E para reparar lo que dejó la heurística.
POLISH_SHARE = 0.15


@dataclass(frozen=True, slots=True)
class StepLog:
    """Un paso del orquestador, para el registro de la ventana de Optimización."""

    phase: str
    elapsed: float
    total: int
    detail: str = ""


@dataclass(frozen=True, slots=True)
class OptimizeResult:
    """Resultado de una estrategia completa."""

    strategy: Strategy
    timetable: Timetable
    evaluation: Evaluation
    elapsed: float
    steps: tuple[StepLog, ...] = field(default_factory=tuple)
    cancelled: bool = False


def _evaluate(ev: Evaluator, tt: Timetable, w: Weighting | None) -> Evaluation:
    return ev.evaluate(tt, w)


def run_strategy(
    project: UntisProject,
    strategy: Strategy,
    *,
    reference: Timetable | None = None,
    weighting: Weighting | None = None,
    seed: int = 0,
    time_limit: float | None = None,
    placement_share: float = 1.0,
    optimize_teachers: bool = False,
    polish: bool = True,
    timetable_id: str = "opt",
    on_progress: Callable[[Progress], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> OptimizeResult:
    """Ejecuta una estrategia A/B/D/E/Reparar y devuelve el mejor horario."""
    t0 = time.perf_counter()
    ev = Evaluator(project)
    referencia = reference if reference is not None else next(iter(project.timetables), None)
    pasos: list[StepLog] = []

    def parar() -> bool:
        return should_stop is not None and should_stop()

    def registrar(fase: str, tt: Timetable, detalle: str = "") -> Evaluation:
        e = _evaluate(ev, tt, weighting)
        pasos.append(StepLog(fase, time.perf_counter() - t0, e.total, detalle))
        return e

    if strategy is Strategy.REPAIR:
        if referencia is None:
            raise ValueError("Reparar necesita un horario de partida")
        limite = time_limit if time_limit is not None else 30.0
        registrar("inicio", referencia)
        rep: RepairOutcome = repair(
            project,
            referencia,
            time_limit=limite * 0.7,
            seed=seed,
            optimize_teachers=optimize_teachers,
            should_stop=should_stop,
            timetable_id=timetable_id,
        )
        actual = rep.timetable if rep.status in ("repaired", "partial") else referencia
        mejor_e = registrar("cp-sat", actual, rep.message)
        if polish and not parar():
            h = heuristic_optimize(
                project,
                strategy=Strategy.REPAIR,
                reference=actual,
                weighting=weighting,
                seed=seed,
                time_limit=max(1.0, limite * 0.3),
                timetable_id=timetable_id,
                on_progress=on_progress,
                should_stop=should_stop,
            )
            if h.evaluation.total <= mejor_e.total:
                actual, mejor_e = h.timetable, registrar("pulido", h.timetable)
        return OptimizeResult(
            strategy, actual, mejor_e, time.perf_counter() - t0, tuple(pasos), parar()
        )

    reparto = 0.0 if strategy is Strategy.A or not polish else POLISH_SHARE
    limite_h = None if time_limit is None else time_limit * (1.0 - reparto)
    share = placement_share
    if strategy is Strategy.D and share >= 1.0:
        share = 0.8
    h: HeuristicResult = heuristic_optimize(
        project,
        strategy=strategy,
        reference=referencia,
        weighting=weighting,
        seed=seed,
        time_limit=limite_h,
        placement_share=share,
        timetable_id=timetable_id,
        on_progress=on_progress,
        should_stop=should_stop,
    )
    actual = h.timetable
    mejor_e = registrar(
        "heurística",
        actual,
        f"{h.iterations} iteraciones, {h.restarts} reinicio(s), "
        f"{len(h.unplaced)} sesión(es) sin colocar",
    )

    necesita = mejor_e.clashes > 0 or mejor_e.unplaced_periods > 0
    if reparto > 0 and necesita and not parar():
        limite_cp = (time_limit * reparto) if time_limit is not None else 60.0
        rep = repair(
            project,
            actual,
            time_limit=limite_cp,
            seed=seed,
            optimize_teachers=optimize_teachers,
            should_stop=should_stop,
            timetable_id=timetable_id,
        )
        if rep.status in ("repaired", "partial"):
            e = _evaluate(ev, rep.timetable, weighting)
            if e.total < mejor_e.total:
                actual, mejor_e = rep.timetable, registrar("cp-sat", rep.timetable, rep.message)

    return OptimizeResult(
        strategy, actual, mejor_e, time.perf_counter() - t0, tuple(pasos), parar()
    )


__all__ = ["POLISH_SHARE", "OptimizeResult", "StepLog", "run_strategy"]
