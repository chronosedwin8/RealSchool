"""Fase 1: colocación por dificultad (como Untis).

Las sesiones se colocan de la lección más difícil a la más fácil; cada una va
a la celda admitida y factible de **menor coste incremental** (delta exacto del
número de evaluación). Las lecciones que piden dobles se colocan por parejas en
períodos consecutivos. Si una sesión no cabe en ninguna celda se intenta una
reparación corta: expulsar hasta dos sesiones que la bloquean (nunca fijadas, y
cada una un número acotado de veces) y volver a encolarlas. Si tampoco, la
sesión queda **sin colocar**: Untis prefiere eso a romper una dura.
"""

from __future__ import annotations

import random
from collections import Counter, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .incremental import Change, State, runs
from .model import Model, cell_code

#: Veces que una misma sesión puede ser expulsada durante la colocación.
MAX_EJECTIONS_PER_SESSION = 3
#: Bloqueadores como máximo que se expulsan para colocar una sesión.
MAX_EJECTED_AT_ONCE = 2


@dataclass(slots=True)
class PlacementStats:
    """Resumen de una colocación."""

    placed: int = 0
    ejections: int = 0
    failed: int = 0


def lesson_order(
    model: Model, difficulty: Sequence[float], rng: random.Random, noise: float = 0.0
) -> list[int]:
    """Lecciones de la más difícil a la más fácil (con ruido para reinicios)."""
    claves = [
        (difficulty[li] * (1.0 + noise * (rng.random() - 0.5)), -li)
        for li in range(len(model.lessons))
    ]
    return sorted(range(len(model.lessons)), key=lambda li: claves[li], reverse=True)


def session_order(model: Model, lessons: Sequence[int]) -> list[int]:
    """Sesiones en el orden de sus lecciones."""
    return [s for li in lessons for s in model.lessons[li].sids]


def reserved_by_share(model: Model, lessons: Sequence[int], share: float) -> frozenset[int]:
    """Sesiones lectivas que quedan fuera de la parte `share` más difícil.

    Estrategia D: la heurística coloca solo esa fracción y deja el resto sin
    colocar para el pulido CP-SAT. Las obligaciones (sin alumnos) no se
    traducen a CP-SAT, así que siempre las coloca la heurística.
    """
    if share >= 1.0:
        return frozenset()
    lectivas = sum(len(L.sids) for L in model.lessons if not L.duty)
    cupo = share * lectivas
    acumulado = 0
    fuera: set[int] = set()
    for li in lessons:
        L = model.lessons[li]
        if L.duty or L.fixed:
            continue
        if acumulado >= cupo:
            fuera.update(L.sids)
        acumulado += len(L.sids)
    return frozenset(fuera)


def load_reference(state: State, order: Sequence[int]) -> int:
    """Coloca cada sesión en su celda de referencia si es factible (REPARAR).

    Devuelve cuántas quedan en su sitio. Las que chocan con algo ya colocado
    quedan sin colocar para la reparación.
    """
    m = state.m
    colocadas = 0
    for s in order:
        c = m.s_ref[s]
        if c < 0 or c not in m.s_allowed_set[s] or state.cell[s] >= 0:
            continue
        L = m.lessons[m.s_lesson[s]]
        d = state.apply([(s, c, L.ref_rooms.get(c))])
        if d is None:
            d = state.apply([(s, c, None)])
        if d is not None:
            state.commit()
            colocadas += 1
    return colocadas


def _next_cell(model: Model, sid: int, cell: int) -> int:
    """Celda del período lectivo siguiente en la rejilla de la sesión (-1 si no hay)."""
    L = model.lessons[model.s_lesson[sid]]
    g = model.grids[L.grid]
    q = g.pos[cell & 0xFF]
    if q < 0 or q + 1 >= len(g.teaching):
        return -1
    return cell_code(cell >> 8, g.teaching[q + 1])


def _best_single(state: State, sid: int, rng: random.Random, noise: float) -> tuple[float, int]:
    mejor = float("inf")
    celda = -1
    for c in state.m.s_allowed[sid]:
        if not state.fits(sid, c):
            continue
        d = state.apply([(sid, c, None)])
        if d is None:
            continue
        state.undo()
        valor = d + noise * rng.random() if noise else float(d)
        if valor < mejor:
            mejor = valor
            celda = c
    return mejor, celda


def _best_pair(
    state: State, sid: int, partner: int, rng: random.Random, noise: float
) -> tuple[float, int, int]:
    m = state.m
    mejor = float("inf")
    par = (-1, -1)
    for c in m.s_allowed[sid]:
        c2 = _next_cell(m, sid, c)
        if c2 < 0 or c2 not in m.s_allowed_set[partner]:
            continue
        if not state.fits(sid, c) or not state.fits(partner, c2):
            continue
        d = state.apply([(sid, c, None), (partner, c2, None)])
        if d is None:
            continue
        state.undo()
        valor = d + noise * rng.random() if noise else float(d)
        if valor < mejor:
            mejor = valor
            par = (c, c2)
    return mejor, par[0], par[1]


def _eject_and_place(
    state: State,
    sid: int,
    ejected: Counter[int],
    frozen: frozenset[int],
) -> list[int] | None:
    """Coloca `sid` expulsando a lo sumo `MAX_EJECTED_AT_ONCE` bloqueadores."""
    m = state.m
    mejor: tuple[int, int] | None = None
    cambios_mejor: list[Change] = []
    fuera_mejor: list[int] = []
    for c in m.s_allowed[sid]:
        if any(s2 != sid and state.cell[s2] == c for s2 in m.lessons[m.s_lesson[sid]].sids):
            continue
        bloq = state.blockers(sid, c)
        if len(bloq) > MAX_EJECTED_AT_ONCE:
            continue
        if any(
            m.s_fixed[b] or b in frozen or ejected[b] >= MAX_EJECTIONS_PER_SESSION for b in bloq
        ):
            continue
        cambios: list[Change] = [(b, -1, None) for b in bloq]
        cambios.append((sid, c, None))
        d = state.apply(cambios)
        if d is None:
            continue
        state.undo()
        clave = (len(bloq), d)
        if mejor is None or clave < mejor:
            mejor = clave
            cambios_mejor = cambios
            fuera_mejor = bloq
    if mejor is None or state.apply(cambios_mejor) is None:
        return None
    state.commit()
    return fuera_mejor


def construct(
    state: State,
    order: Sequence[int],
    rng: random.Random,
    *,
    frozen: frozenset[int] = frozenset(),
    noise: float = 0.0,
    stop: Callable[[], bool] | None = None,
    on_step: Callable[[int], None] | None = None,
) -> PlacementStats:
    """Coloca las sesiones de `order` (las ya colocadas o congeladas se saltan)."""
    m = state.m
    stats = PlacementStats()
    cola: deque[int] = deque(s for s in order if s not in frozen)
    expulsadas: Counter[int] = Counter()
    paso = 0
    while cola:
        paso += 1
        if stop is not None and paso % 8 == 0 and stop():
            break
        if on_step is not None and paso % 64 == 0:
            on_step(paso)
        s = cola.popleft()
        if state.cell[s] >= 0 or not m.s_allowed[s]:
            continue
        L = m.lessons[m.s_lesson[s]]
        # Dobles: si la lección aún no tiene los que pide, se colocan por parejas.
        pareja = -1
        if L.dp_min:
            hechos = _doubles_of(state, L.index)
            if hechos < L.dp_min:
                for s2 in L.sids:
                    if s2 != s and state.cell[s2] < 0 and s2 not in frozen:
                        pareja = s2
                        break
        if pareja >= 0:
            _, c1, c2 = _best_pair(state, s, pareja, rng, noise)
            if c1 >= 0 and state.apply([(s, c1, None), (pareja, c2, None)]) is not None:
                state.commit()
                stats.placed += 2
                continue
        _, c = _best_single(state, s, rng, noise)
        if c >= 0 and state.apply([(s, c, None)]) is not None:
            state.commit()
            stats.placed += 1
            continue
        fuera = _eject_and_place(state, s, expulsadas, frozen)
        if fuera is None:
            stats.failed += 1
            continue
        stats.placed += 1
        stats.ejections += len(fuera)
        for b in fuera:
            expulsadas[b] += 1
            cola.appendleft(b)
    return stats


def _doubles_of(state: State, li: int) -> int:
    """Períodos dobles que ya tiene la lección (tramos consecutivos // 2)."""
    m = state.m
    L = m.lessons[li]
    g = m.grids[L.grid]
    por_dia: dict[int, int] = {}
    for s in L.sids:
        c = state.cell[s]
        if c >= 0:
            q = g.pos[c & 0xFF]
            if q >= 0:
                por_dia[c >> 8] = por_dia.get(c >> 8, 0) | (1 << q)
    return sum(r // 2 for mk in por_dia.values() for r in runs(mk))
