"""Fase 2: intercambios con recocido simulado.

En cada iteración se elige un tipo de movimiento (`moves`), se aplica con
delta exacto y se acepta por Metropolis: siempre si no empeora, y si empeora
con probabilidad `exp(-delta / T)`. La temperatura baja geométricamente de
`t0` a `t_end` a lo largo del presupuesto: por iteraciones si se fija
`max_iterations` (entonces la corrida es determinista para una semilla), o por
tiempo si no.

El mejor horario visto se guarda como copia de celdas y aulas y se devuelve
al terminar; la corrida puede pararse en cualquier momento (`stop`).
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from scheduling_platform.untis_model.weighting import UNPLACED_PENALTY

from .incremental import State
from .moves import MoveGenerator

#: Peso relativo de cada tipo de movimiento.
MOVE_WEIGHTS: dict[str, float] = {
    "relocate": 3.0,
    "chain": 3.0,
    "entity_swap": 2.0,
    "double": 1.0,
    "room": 0.5,
    "insert": 2.0,
}

#: Iteraciones entre dos comprobaciones de reloj y de `stop`.
CHECK_EVERY = 64


@dataclass(slots=True)
class AnnealResult:
    """Resultado de una corrida de recocido."""

    iterations: int = 0
    evaluated: int = 0
    accepted: int = 0
    best_objective: int = 0
    best_total: int = 0
    best_unplaced: int = 0
    best_cells: list[int] = field(default_factory=list)
    best_rooms: list[tuple[int, ...]] = field(default_factory=list)


def calibrate(state: State, gen: MoveGenerator, rng: random.Random, samples: int = 300) -> float:
    """Temperatura inicial: media de los empeoramientos blandos de movimientos al azar.

    Aplica y deshace `samples` movimientos; el estado no cambia.
    """
    positivos: list[int] = []
    intentos = 0
    while len(positivos) < samples and intentos < samples * 50:
        intentos += 1
        _, f = gen.kinds[rng.randrange(3)]
        cambios = f()
        if cambios is None:
            continue
        d = state.apply(cambios)
        if d is None:
            continue
        state.undo()
        if 0 < d < UNPLACED_PENALTY // 2:
            positivos.append(d)
    if not positivos:
        return 10.0
    return max(1.0, sum(positivos) / len(positivos))


def anneal(
    state: State,
    gen: MoveGenerator,
    rng: random.Random,
    *,
    t0: float,
    t_end: float = 0.5,
    max_iterations: int | None = None,
    time_budget: float | None = None,
    stop: Callable[[], bool] | None = None,
    patience: int | None = None,
    on_tick: Callable[[int, int, int, int], None] | None = None,
    on_improve: Callable[[int], None] | None = None,
) -> AnnealResult:
    """Recocido simulado sobre `state`; devuelve el mejor horario visto.

    `on_tick(iteración, actual, mejor, sin_colocar_mejor)` se llama cada
    `CHECK_EVERY` iteraciones; `on_improve(total)` cada vez que mejora el mejor.
    Con `patience`, la corrida termina tras ese número de iteraciones sin
    mejorar el mejor (REPARAR converge enseguida y no debe agotar el tiempo).
    """
    if max_iterations is None and time_budget is None:
        raise ValueError("El recocido necesita max_iterations o time_budget")
    tipos = [(nombre, f) for nombre, f in gen.kinds if MOVE_WEIGHTS.get(nombre, 0.0) > 0]
    pesos = [MOVE_WEIGHTS[nombre] for nombre, _ in tipos]
    acumulado: list[float] = []
    suma = 0.0
    for p in pesos:
        suma += p
        acumulado.append(suma)
    indice_insertar = next(i for i, (n, _) in enumerate(tipos) if n == "insert")

    res = AnnealResult()
    mejor = state.objective
    res.best_objective = mejor
    res.best_total = state.total
    res.best_unplaced = state.unplaced_count()
    res.best_cells, res.best_rooms = state.snapshot()
    mejor_es_actual = True

    inicio = time.perf_counter()
    t = t0
    ratio = t_end / t0 if t0 > 0 else 1.0
    it = 0
    ultima_mejora = 0
    random_ = rng.random
    exp = math.exp
    while True:
        if it % CHECK_EVERY == 0:
            if stop is not None and stop():
                break
            if max_iterations is not None:
                if it >= max_iterations:
                    break
                frac = it / max_iterations
            else:
                assert time_budget is not None
                transcurrido = time.perf_counter() - inicio
                if transcurrido >= time_budget:
                    break
                frac = transcurrido / time_budget if time_budget > 0 else 1.0
            t = t0 * ratio**frac
            if patience is not None and it - ultima_mejora >= patience:
                break
            if on_tick is not None:
                on_tick(it, state.total, res.best_total, res.best_unplaced)
        it += 1
        x = random_() * suma
        k = 0
        while acumulado[k] < x:
            k += 1
        if k == indice_insertar and not gen.insertable:
            k = 0
        cambios = tipos[k][1]()
        if cambios is None:
            continue
        d = state.apply(cambios)
        if d is None:
            continue
        res.evaluated += 1
        if d <= 0 or (t > 0 and random_() < exp(-d / t)):
            if d > 0 and mejor_es_actual:
                # Se abandona el mejor: se guarda reconstruyéndolo desde el deshacer.
                res.best_cells, res.best_rooms = _before(state)
                mejor_es_actual = False
            state.commit()
            res.accepted += 1
            if k == indice_insertar or any(c < 0 for _, c, _ in cambios):
                gen.refresh_unplaced()
            if state.objective < mejor:
                mejor = state.objective
                res.best_objective = mejor
                res.best_total = state.total
                res.best_unplaced = state.unplaced_count()
                mejor_es_actual = True
                ultima_mejora = it
                if on_improve is not None:
                    on_improve(state.total)
            elif d > 0:
                mejor_es_actual = False
        else:
            state.undo()
    if mejor_es_actual:
        res.best_cells, res.best_rooms = state.snapshot()
    res.iterations = it
    return res


def _before(state: State) -> tuple[list[int], list[tuple[int, ...]]]:
    """Celdas y aulas del estado **antes** del último `apply` (aún sin confirmar)."""
    cells, rooms = state.snapshot()
    u = state.last_undo()
    for sid, _ in u.new:
        cells[sid] = -1
    for sid, c, r in u.old:
        cells[sid] = c
        rooms[sid] = r
    return cells, rooms
