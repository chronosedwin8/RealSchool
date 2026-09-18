"""Estrategias de optimización de Untis (A, B, D, E) y REPARAR.

- **A (rápida)**: colocación + intercambios cortos, una corrida (60 s).
- **B (compleja)**: una corrida larga desde cero y varios reinicios que
  recalientan el recocido desde el mejor horario, cada uno con su semilla;
  se queda con el mejor (600 s).
- **D (colocación %)**: como B, pero la fase 1 coloca solo la fracción más
  difícil y deja el resto sin colocar para el pulido CP-SAT (600 s).
- **E (nocturna)**: B larga con más corridas (1800 s).
- **REPARAR**: parte del horario de referencia, deja en su sitio todo lo
  factible y recoloca solo lo que choca o falta, con un coste por sesión movida
  (cambio mínimo, 20 s como máximo).

El pulido CP-SAT (fase 3) no vive aquí: lo orquesta `bridge` con este resultado.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from scheduling_platform.untis_model.evaluation import Evaluator
from scheduling_platform.untis_model.project import UntisProject
from scheduling_platform.untis_model.timetable import Evaluation, Timetable
from scheduling_platform.untis_model.weighting import Weighting

from .annealing import anneal, calibrate
from .difficulty import lesson_difficulty
from .incremental import State, load
from .model import Model, build_model
from .moves import MoveGenerator
from .placement import (
    construct,
    lesson_order,
    load_reference,
    reserved_by_share,
    session_order,
)


class Strategy(StrEnum):
    """Estrategia de optimización, como en el diálogo de Untis."""

    A = "A"
    B = "B"
    D = "D"
    E = "E"
    REPAIR = "repair"


#: Presupuesto por defecto (s) cuando el llamador no fija `time_limit`.
DEFAULT_TIME: Final[dict[Strategy, float]] = {
    Strategy.A: 60.0,
    Strategy.B: 600.0,
    Strategy.D: 600.0,
    Strategy.E: 1800.0,
    Strategy.REPAIR: 20.0,
}

#: Corridas independientes (1 + reinicios) por estrategia.
RUNS: Final[dict[Strategy, int]] = {
    Strategy.A: 1,
    Strategy.B: 3,
    Strategy.D: 3,
    Strategy.E: 5,
    Strategy.REPAIR: 1,
}

#: Fracción colocada por D cuando el llamador deja `placement_share=1.0`.
DEFAULT_D_SHARE: Final = 0.8

#: Temperatura inicial = factor x empeoramiento medio de un movimiento al azar.
T0_FACTOR: Final = 0.05
#: Temperatura final del recocido.
T_END: Final = 0.2
#: Temperatura inicial de REPARAR (casi un descenso puro).
REPAIR_T0: Final = 1.0
#: Iteraciones sin mejora tras las que REPARAR da por terminada la corrida.
REPAIR_PATIENCE: Final = 50_000
#: Fracción del presupuesto de la primera corrida cuando hay reinicios.
FIRST_RUN_SHARE: Final = 0.5
#: Temperatura inicial de un reinicio respecto a la de la primera corrida.
REHEAT_FACTOR: Final = 0.5


@dataclass(frozen=True, slots=True)
class Progress:
    """Aviso de progreso para la UI."""

    phase: str
    """`placement`, `improvement` o `restart`."""
    iteration: int
    current: int
    """Número de evaluación actual."""
    best: int
    """Mejor número de evaluación hasta ahora."""
    unplaced: int
    """Períodos sin colocar del mejor."""
    elapsed: float
    """Segundos desde el inicio."""


@dataclass(frozen=True, slots=True)
class HeuristicResult:
    """Resultado de `optimize`."""

    timetable: Timetable
    evaluation: Evaluation
    """Igual a `Evaluator(project).evaluate(timetable, weighting)`."""
    unplaced: tuple[tuple[int, int], ...]
    """`(nº de lección, índice de sesión)` que quedaron sin colocar."""
    iterations: int
    elapsed: float
    restarts: int
    history: tuple[tuple[float, int], ...]
    """`(segundos, mejor número de evaluación)` en cada mejora."""


def repair_change_penalty(weighting: Weighting) -> int:
    """Coste de mover una sesión en REPARAR: más que cualquier violación suelta."""
    return max(5000, 10 * max(weighting.weight(c) for c in Weighting.criteria()))


class _Run:
    """Contexto compartido por las corridas de una optimización."""

    def __init__(
        self,
        started: float,
        deadline: float,
        should_stop: Callable[[], bool] | None,
        on_progress: Callable[[Progress], None] | None,
    ) -> None:
        self.started = started
        self.deadline = deadline
        self.should_stop = should_stop
        self.on_progress = on_progress
        self.history: list[tuple[float, int]] = []
        self.best_total: int | None = None
        self.best_unplaced = 0
        self.iterations = 0
        self._last_report = 0.0

    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    def stopped(self) -> bool:
        if self.should_stop is not None and self.should_stop():
            return True
        return time.perf_counter() >= self.deadline

    def improved(self, total: int, unplaced: int) -> None:
        if self.best_total is None or total < self.best_total:
            self.best_total = total
            self.best_unplaced = unplaced
            ahora = self.elapsed()
            if not self.history or ahora - self.history[-1][0] >= 0.05:
                self.history.append((ahora, total))
            else:
                self.history[-1] = (self.history[-1][0], total)

    def report(self, phase: str, iteration: int, current: int, *, force: bool = False) -> None:
        if self.on_progress is None:
            return
        ahora = self.elapsed()
        if not force and ahora - self._last_report < 0.25:
            return
        self._last_report = ahora
        mejor = self.best_total if self.best_total is not None else current
        self.on_progress(
            Progress(
                phase=phase,
                iteration=self.iterations + iteration,
                current=current,
                best=mejor,
                unplaced=self.best_unplaced,
                elapsed=ahora,
            )
        )


def _one_run(
    model: Model,
    strategy: Strategy,
    index: int,
    runs: int,
    seed: int,
    ctx: _Run,
    max_iterations: int | None,
    start: tuple[list[int], list[tuple[int, ...]]] | None,
    frozen: frozenset[int],
) -> tuple[int, list[int], list[tuple[int, ...]], int]:
    """Una corrida. Devuelve `(objetivo, celdas, aulas, iteraciones)`.

    La primera corrida coloca desde cero (o desde la referencia en REPARAR);
    las siguientes recalientan el recocido desde el mejor horario (`start`).
    """
    rng = random.Random(seed * 1_000_003 + index)
    state = State(model)
    fase = "placement" if start is None else "restart"
    ctx.report(fase, 0, state.total, force=True)
    if start is None:
        dificultad = [L.difficulty for L in model.lessons]
        orden = session_order(model, lesson_order(model, dificultad, rng))
        if strategy is Strategy.REPAIR:
            load_reference(state, orden)

        def paso(_: int) -> None:
            ctx.report(fase, 0, state.total)

        construct(state, orden, rng, frozen=frozen, stop=ctx.stopped, on_step=paso)
    else:
        load(state, start[0], start[1])
    ctx.improved(state.total, state.unplaced_count())
    ctx.report(fase, 0, state.total, force=True)

    gen = MoveGenerator(state, rng, frozen=frozen)
    reparar = strategy is Strategy.REPAIR
    t0 = REPAIR_T0 if reparar else T0_FACTOR * calibrate(state, gen, rng)
    if start is not None:
        t0 *= REHEAT_FACTOR
    # La primera corrida se lleva `FIRST_RUN_SHARE` del tiempo; el resto, a partes iguales.
    peso = 1.0 if runs == 1 else FIRST_RUN_SHARE if index == 0 else 1.0 - FIRST_RUN_SHARE
    parte = peso if index == 0 or runs == 1 else peso / (runs - 1)
    presupuesto: float | None = None
    iteraciones: int | None = None
    if max_iterations is not None:
        iteraciones = int(max_iterations * parte)
    else:
        restante_total = max(0.0, ctx.deadline - time.perf_counter())
        # Fracción del tiempo que aún queda que corresponde a esta corrida.
        pendiente = 1.0 if index == 0 else (runs - index) * (1.0 - FIRST_RUN_SHARE) / (runs - 1)
        presupuesto = restante_total * min(1.0, parte / pendiente) if pendiente > 0 else 0.0

    def tick(it: int, actual: int, _mejor: int, _sin: int) -> None:
        ctx.report("improvement", it, actual)

    def mejora(total: int) -> None:
        ctx.improved(total, state.unplaced_count())

    res = anneal(
        state,
        gen,
        rng,
        t0=t0,
        t_end=min(T_END, t0),
        max_iterations=iteraciones,
        time_budget=presupuesto,
        stop=ctx.stopped,
        patience=REPAIR_PATIENCE if strategy is Strategy.REPAIR else None,
        on_tick=tick,
        on_improve=mejora,
    )
    ctx.iterations += res.iterations
    return res.best_objective, res.best_cells, res.best_rooms, res.iterations


def optimize(
    project: UntisProject,
    *,
    strategy: Strategy = Strategy.A,
    reference: Timetable | None = None,
    weighting: Weighting | None = None,
    seed: int = 0,
    time_limit: float | None = None,
    placement_share: float = 1.0,
    timetable_id: str = "heuristic",
    on_progress: Callable[[Progress], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    max_iterations: int | None = None,
) -> HeuristicResult:
    """Genera un horario con la heurística de dos fases de Untis.

    `reference` fija las duraciones de las sesiones y es el punto de partida de
    REPARAR (por defecto, el primer horario del proyecto). `time_limit` en
    segundos (por defecto, el de la estrategia) y `should_stop()` se respetan
    siempre. Con `max_iterations` el recocido cuenta iteraciones en vez de
    tiempo y el resultado es determinista para una `seed` dada.
    """
    inicio = time.perf_counter()
    estrategia = Strategy(strategy)
    w = weighting if weighting is not None else project.weighting
    ref = reference
    if ref is None and project.timetables:
        ref = project.timetables[0]
    limite = time_limit if time_limit is not None else DEFAULT_TIME[estrategia]
    share = placement_share
    if estrategia is Strategy.D and share >= 1.0:
        share = DEFAULT_D_SHARE
    share = min(1.0, max(0.0, share))
    penal = repair_change_penalty(w) if estrategia is Strategy.REPAIR else 0

    model = build_model(project, ref, w, change_penalty=penal)
    for L, d in zip(model.lessons, lesson_difficulty(model), strict=True):
        L.difficulty = d
    ctx = _Run(inicio, inicio + limite, should_stop, on_progress)

    corridas = RUNS[estrategia]
    dificultad = [L.difficulty for L in model.lessons]
    congeladas = reserved_by_share(
        model, lesson_order(model, dificultad, random.Random(seed)), share
    )
    mejor: tuple[int, list[int], list[tuple[int, ...]]] | None = None
    hechas = 0
    for i in range(corridas):
        if i > 0 and ctx.stopped():
            break
        inicio_corrida = (mejor[1], mejor[2]) if mejor is not None else None
        objetivo, celdas, aulas, _ = _one_run(
            model,
            estrategia,
            i,
            corridas,
            seed,
            ctx,
            max_iterations,
            inicio_corrida,
            congeladas,
        )
        hechas += 1
        if mejor is None or objetivo < mejor[0]:
            mejor = (objetivo, celdas, aulas)
    assert mejor is not None

    final = State(model)
    load(final, mejor[1], mejor[2])
    horario = final.to_timetable(timetable_id)
    evaluacion = Evaluator(project).evaluate(horario, w)
    horario = Timetable(
        id=horario.id, name=horario.name, assignments=horario.assignments, evaluation=evaluacion
    )
    sin_colocar = tuple(
        (model.lessons[model.s_lesson[s]].number, model.s_index[s])
        for s in final.unplaced_sessions()
    )
    ctx.improved(evaluacion.total, evaluacion.unplaced_periods)
    transcurrido = ctx.elapsed()
    historia = list(ctx.history)
    if not historia or historia[-1][1] != evaluacion.total:
        historia.append((transcurrido, evaluacion.total))
    ctx.report("improvement", 0, evaluacion.total, force=True)
    return HeuristicResult(
        timetable=horario,
        evaluation=evaluacion,
        unplaced=sin_colocar,
        iterations=ctx.iterations,
        elapsed=transcurrido,
        restarts=max(0, hechas - 1),
        history=tuple(historia),
    )
