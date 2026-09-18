"""Vecindario de la fase de intercambios.

Cada generador propone una lista de cambios (`Change`) sobre el estado actual;
`State.apply` los valida contra las duras y devuelve el delta exacto. Los
movimientos replican los de Untis:

- **mover**: una sesión a otra celda admitida;
- **intercambio en cadena** (Kempe): la sesión va a una celda ocupada y las
  sesiones que la bloquean (hasta tres) pasan a la celda que deja libre;
- **intercambio por entidad**: dos sesiones de la misma clase o profesor
  intercambian celdas;
- **doble**: una pareja de sesiones consecutivas de la misma lección se mueve
  junta, conservando el período doble;
- **aula**: una línea cambia a otra aula candidata libre;
- **insertar**: una sesión sin colocar entra en una celda y, si hace falta,
  desplaza a quienes la bloquean a otra celda (o los deja sin colocar).
"""

from __future__ import annotations

import random
from collections.abc import Callable

from .incremental import Change, State
from .model import cell_code

#: Bloqueadores como máximo en un intercambio en cadena.
MAX_CHAIN = 3


class MoveGenerator:
    """Propone movimientos aleatorios sobre un `State`."""

    def __init__(
        self, state: State, rng: random.Random, *, frozen: frozenset[int] = frozenset()
    ) -> None:
        m = state.m
        self.state = state
        self.rng = rng
        self.frozen = frozen
        """Sesiones que la heurística no toca (reservadas para CP-SAT)."""
        self.movable: list[int] = [
            s
            for s in range(m.nsessions)
            if not m.s_fixed[s] and len(m.s_allowed[s]) > 1 and s not in frozen
        ]
        self.movable_set = frozenset(self.movable)
        self.lective_movable: list[int] = [
            s for s in self.movable if not m.lessons[m.s_lesson[s]].duty
        ]
        self.room_movable: list[int] = [
            s
            for s in self.movable
            if any(len(x.candidates) > 1 for x in m.lessons[m.s_lesson[s]].lines)
        ]
        self.insertable: list[int] = []
        self.refresh_unplaced()
        self.kinds: list[tuple[str, Callable[[], list[Change] | None]]] = [
            ("relocate", self.relocate),
            ("chain", self.chain),
            ("entity_swap", self.entity_swap),
            ("double", self.double),
            ("room", self.room),
            ("insert", self.insert),
        ]

    # ------------------------------------------------------------------ #

    def refresh_unplaced(self) -> None:
        """Recalcula la lista de sesiones sin colocar que se pueden insertar."""
        m = self.state.m
        self.insertable = [
            s for s in self.state.unplaced_sessions() if s not in self.frozen and m.s_allowed[s]
        ]

    def _placed_movable(self, pool: list[int]) -> int:
        """Una sesión colocada y movible al azar (-1 si no la encuentra)."""
        if not pool:
            return -1
        cell = self.state.cell
        for _ in range(8):
            s = pool[self.rng.randrange(len(pool))]
            if cell[s] >= 0:
                return s
        return -1

    def _sibling_at(self, sid: int, cell: int) -> bool:
        m = self.state.m
        c = self.state.cell
        return any(s2 != sid and c[s2] == cell for s2 in m.lessons[m.s_lesson[sid]].sids)

    # ------------------------------------------------------------------ #
    # Movimientos
    # ------------------------------------------------------------------ #

    def relocate(self) -> list[Change] | None:
        """Mueve una sesión a otra celda admitida libre."""
        st = self.state
        s = self._placed_movable(self.movable)
        if s < 0:
            return None
        permitidas = st.m.s_allowed[s]
        c = permitidas[self.rng.randrange(len(permitidas))]
        if c == st.cell[s] or not st.fits(s, c):
            return None
        return [(s, c, None)]

    def chain(self) -> list[Change] | None:
        """Kempe: la sesión va a una celda ocupada y sus bloqueadores a la suya."""
        st = self.state
        m = st.m
        s = self._placed_movable(self.lective_movable)
        if s < 0:
            return None
        permitidas = m.s_allowed[s]
        c = permitidas[self.rng.randrange(len(permitidas))]
        vieja = st.cell[s]
        if c == vieja or self._sibling_at(s, c):
            return None
        bloq = st.blockers(s, c)
        if not bloq:
            return [(s, c, None)]
        if len(bloq) > MAX_CHAIN:
            return None
        li = m.s_lesson[s]
        cambios: list[Change] = [(s, c, None)]
        for b in bloq:
            if b not in self.movable_set or m.s_lesson[b] == li or vieja not in m.s_allowed_set[b]:
                return None
            cambios.append((b, vieja, None))
        return cambios

    def entity_swap(self) -> list[Change] | None:
        """Intercambia dos sesiones de un mismo profesor o clase."""
        st = self.state
        m = st.m
        rng = self.rng
        s = self._placed_movable(self.lective_movable)
        if s < 0:
            return None
        L = m.lessons[m.s_lesson[s]]
        if not L.entities:
            return None
        e = L.entities[rng.randrange(len(L.entities))]
        k = e * st.nd + rng.randrange(st.nd)
        lista = st.ed[k]
        if not lista:
            return None
        s2 = lista[rng.randrange(len(lista))]
        if s2 == s or s2 not in self.movable_set or m.s_lesson[s2] == L.index:
            return None
        c1 = st.cell[s]
        c2 = st.cell[s2]
        if c2 not in m.s_allowed_set[s] or c1 not in m.s_allowed_set[s2]:
            return None
        return [(s, c2, None), (s2, c1, None)]

    def double(self) -> list[Change] | None:
        """Mueve junta una pareja de sesiones consecutivas de la misma lección."""
        st = self.state
        m = st.m
        rng = self.rng
        s = self._placed_movable(self.movable)
        if s < 0:
            return None
        L = m.lessons[m.s_lesson[s]]
        if len(L.sids) < 2:
            return None
        g = m.grids[L.grid]
        c = st.cell[s]
        d = c >> 8
        q = g.pos[c & 0xFF]
        if q < 0:
            return None
        pareja = -1
        for s2 in L.sids:
            c2 = st.cell[s2]
            if s2 != s and c2 >= 0 and c2 >> 8 == d and g.pos[c2 & 0xFF] == q + 1:
                pareja = s2
                break
        if pareja < 0 or pareja not in self.movable_set:
            return None
        permitidas = m.s_allowed[s]
        nueva = permitidas[rng.randrange(len(permitidas))]
        qn = g.pos[nueva & 0xFF]
        if nueva == c or qn < 0 or qn + 1 >= len(g.teaching):
            return None
        nueva2 = cell_code(nueva >> 8, g.teaching[qn + 1])
        if nueva2 not in m.s_allowed_set[pareja]:
            return None
        return [(s, nueva, None), (pareja, nueva2, None)]

    def room(self) -> list[Change] | None:
        """Cambia el aula de una línea por otra candidata."""
        st = self.state
        m = st.m
        rng = self.rng
        s = self._placed_movable(self.room_movable)
        if s < 0:
            return None
        L = m.lessons[m.s_lesson[s]]
        i = rng.randrange(len(L.lines))
        line = L.lines[i]
        if len(line.candidates) < 2:
            return None
        r = line.candidates[rng.randrange(len(line.candidates))]
        actuales = st.rooms[s]
        if actuales[i] == r:
            return None
        nuevas = (*actuales[:i], r, *actuales[i + 1 :])
        return [(s, st.cell[s], nuevas)]

    def insert(self) -> list[Change] | None:
        """Coloca una sesión sin colocar, desplazando a sus bloqueadores."""
        st = self.state
        m = st.m
        rng = self.rng
        if not self.insertable:
            return None
        s = self.insertable[rng.randrange(len(self.insertable))]
        if st.cell[s] >= 0:
            self.refresh_unplaced()
            return None
        permitidas = m.s_allowed[s]
        c = permitidas[rng.randrange(len(permitidas))]
        if self._sibling_at(s, c):
            return None
        bloq = st.blockers(s, c)
        if not bloq:
            return [(s, c, None)]
        if len(bloq) > 2:
            return None
        cambios: list[Change] = [(s, c, None)]
        for b in bloq:
            if b not in self.movable_set:
                return None
            destino = -1
            opciones = m.s_allowed[b]
            for _ in range(8):
                cb = opciones[rng.randrange(len(opciones))]
                if cb != st.cell[b] and st.fits(b, cb):
                    destino = cb
                    break
            cambios.append((b, destino, None))
        return cambios
