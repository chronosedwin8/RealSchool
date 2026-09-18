"""Evaluación incremental exacta: el número de evaluación por ámbitos locales.

Casi todos los criterios de `untis_model.evaluation` son una suma de funciones
locales:

- por **(entidad, día)**: huecos, períodos por día, media jornada, almuerzo,
  tarde, seguidos, último período (máscara de períodos de la rejilla propia) y,
  en las clases, materias principales, secuencias, adyacencias y "misma materia
  en tramos separados" (lista de sesiones del día);
- por **entidad** (semana): huecos semanales, días por semana, equilibrio de
  carga y deseos no especificados;
- por **lección**: dobles, bloques, mismo día, días seguidos, reparto semanal,
  mismo período en días seguidos, y la suma por sesión de aulas, deseos,
  profesor sin asignar y materia principal por la tarde; más los no colocados.

Los **deseos positivos** (+1..+3, cuestan si la entidad queda libre en la
celda) se llevan aparte con un contador de ocupación por `(entidad, celda)`
deseada: `_add`/`_remove` ajustan `total` al instante cuando una celda pasa de
libre a ocupada o al revés. Es exacto, O(1) por sesión y solo mira las
entidades de la lección (profesores, clases, materia) y sus aulas.

`State` guarda la puntuación cacheada de cada ámbito. Un movimiento solo toca
los ámbitos de las sesiones movidas (día viejo y día nuevo de sus profesores y
clases, y sus lecciones): el delta es la suma de `nuevo - cacheado` sobre esos
ámbitos. Cada función local replica **literalmente** la definición del
evaluador de referencia; un test exige que `State` y `Evaluator.report`
coincidan criterio a criterio tras cada movimiento.

Invariante dura: dos sesiones lectivas de lecciones distintas nunca comparten
profesor, clase o aula en el mismo instante del reloj de pared. `apply`
rechaza (devuelve `None`) cualquier cambio que la rompa.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from scheduling_platform.untis_model.common import EntityKind
from scheduling_platform.untis_model.requests import UnspecifiedKind
from scheduling_platform.untis_model.timetable import (
    Assignment,
    CriterionScore,
    Evaluation,
    Timetable,
)
from scheduling_platform.untis_model.weighting import UNPLACED_PENALTY

from .model import (
    CLASS_DAY,
    CLASS_WEEK,
    CRIT_INDEX,
    CRITERIA,
    LESSON_SCOPE,
    TEACHER_DAY,
    TEACHER_WEEK,
    WISH_CRITERIA,
    LessonInfo,
    Model,
    Profile,
    cell_day,
    cell_period,
)

#: Un cambio: `(sesión, celda nueva o -1, aulas por línea o None = elegir)`.
Change = tuple[int, int, tuple[int, ...] | None]

_ZERO_TD = (0,) * len(TEACHER_DAY)
_ZERO_TW = (0,) * len(TEACHER_WEEK)
_ZERO_CD = (0,) * len(CLASS_DAY)
_ZERO_CW = (0,) * len(CLASS_WEEK)
_ZERO_CS = (0,) * 5
_ZERO_L = (0,) * len(LESSON_SCOPE)


def runs(mask: int) -> list[int]:
    """Longitudes de los tramos de bits consecutivos a 1, de menor a mayor bit."""
    largos: list[int] = []
    while mask:
        mask >>= (mask & -mask).bit_length() - 1
        largo = (~mask & (mask + 1)).bit_length() - 1
        largos.append(largo)
        mask >>= largo
    return largos


def count_runs(mask: int) -> int:
    """Número de tramos de bits consecutivos a 1."""
    return (mask & ~(mask << 1)).bit_count()


def gaps(mask: int) -> int:
    """Huecos: posiciones libres entre el primer y el último bit a 1."""
    n = mask.bit_count()
    if n < 2:
        return 0
    return mask.bit_length() - (mask & -mask).bit_length() + 1 - n


def excess(value: int, lo: int | None, hi: int | None) -> int:
    """`evaluation._minmax_excess`."""
    exceso = 0
    if hi is not None and value > hi:
        exceso += value - hi
    if lo is not None and value < lo:
        exceso += lo - value
    return exceso


@dataclass(slots=True)
class Undo:
    """Lo necesario para deshacer el último `apply`."""

    old: list[tuple[int, int, tuple[int, ...]]]
    new: list[tuple[int, int]]
    ed: list[tuple[int, int, tuple[int, ...], int]]
    ew: list[tuple[int, int, tuple[int, ...]]]
    les: list[tuple[int, int, tuple[int, ...], int]]
    total: int
    extra: int


class State:
    """Horario mutable con puntuación incremental exacta.

    `total` es el número de evaluación, idéntico a `Evaluator.evaluate(...).total`
    (la heurística nunca crea choques); `extra` suma los costes internos que el
    evaluador no cuenta (en REPARAR, las sesiones que se alejan de su celda de
    referencia).
    """

    def __init__(self, model: Model) -> None:
        m = model
        self.m = m
        nd = m.ndays
        self.nd = nd
        nres = len(m.resource_ids)
        nent = len(m.entities)
        self.cell: list[int] = [-1] * m.nsessions
        self.n_unplaced = m.nsessions
        self.rooms: list[tuple[int, ...]] = [(-1,) * len(m.lessons[li].lines) for li in m.s_lesson]
        self.occ: list[int] = [0] * (nres * nd)
        self.rd: list[list[int]] = [[] for _ in range(nres * nd)]
        self.ed: list[list[int]] = [[] for _ in range(nent * nd)]
        self.ed_mask: list[int] = [0] * (nent * nd)
        self.ed_val: list[int] = [0] * (nent * nd)
        self.ed_vec: list[tuple[int, ...]] = [
            _ZERO_CD if m.entities[k // nd].kind is EntityKind.CLASS else _ZERO_TD
            for k in range(nent * nd)
        ]
        self.ew_val: list[int] = [0] * nent
        self.ew_vec: list[tuple[int, ...]] = [
            _ZERO_CW if e.kind is EntityKind.CLASS else _ZERO_TW for e in m.entities
        ]
        self.l_val: list[int] = [0] * len(m.lessons)
        self.l_vec: list[tuple[int, ...]] = [_ZERO_L] * len(m.lessons)
        self.l_ext: list[int] = [0] * len(m.lessons)
        self.busy: dict[tuple[int, int], int] = {}
        """Sesiones lectivas por `(clave, celda)` con deseo positivo."""
        self.wish_v: list[int] = list(m.wish_base)
        """Violaciones de deseos positivos por tipo (`WISH_CRITERIA`)."""
        self._w_wish = m.scope_weights(WISH_CRITERIA)
        self._wish_on = bool(m.wishes)

        self._w_td = m.scope_weights(TEACHER_DAY)
        self._w_tw = m.scope_weights(TEACHER_WEEK)
        self._w_cd = m.scope_weights(CLASS_DAY)
        self._w_cw = m.scope_weights(CLASS_WEEK)
        self._w_l = m.scope_weights(LESSON_SCOPE)
        self._memo: list[dict[int, tuple[int, tuple[int, ...]]]] = [{} for _ in m.profiles]
        self._room_memo: dict[tuple[int, tuple[int, ...]], tuple[int, int, int, int]] = {}
        self._room_costs = bool(m.room_capacity or m.room_requests) or any(
            le.has_room_costs for le in m.lessons
        )
        self._ent_week = [e.kind is EntityKind.TEACHER or bool(e.unspecified) for e in m.entities]
        self._ded: set[int] = set()
        self._dles: set[int] = set()
        self._undo: Undo | None = None

        self.total = self._wish_total()
        self.extra = 0
        for e in range(nent):
            val, vec = self._week(e)
            self.ew_val[e] = val
            self.ew_vec[e] = vec
            self.total += val
        for li in range(len(m.lessons)):
            val, vec, ext = self._lesson(li)
            self.l_val[li] = val
            self.l_vec[li] = vec
            self.l_ext[li] = ext
            self.total += val
            self.extra += ext

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #

    @property
    def objective(self) -> int:
        """Lo que minimiza la heurística: evaluación + costes internos."""
        return self.total + self.extra

    def placed(self, sid: int) -> bool:
        """`True` si la sesión está colocada."""
        return self.cell[sid] >= 0

    def unplaced_sessions(self) -> list[int]:
        """Sesiones sin colocar, en orden de sid."""
        return [s for s, c in enumerate(self.cell) if c < 0]

    def unplaced_count(self) -> int:
        """Sesiones sin colocar (contador mantenido por `_add`/`_remove`)."""
        return self.n_unplaced

    def fits(self, sid: int, cell: int) -> bool:
        """`True` si profesores y clases de la sesión están libres en `cell`.

        No mira aulas (las elige `apply`). La sesión debe estar sin colocar o
        se comprobará contra sí misma.
        """
        m = self.m
        L = m.lessons[m.s_lesson[sid]]
        for s2 in L.sids:
            if s2 != sid and self.cell[s2] == cell:
                return False
        if L.duty:
            return True
        em = m.grids[L.grid].emask[cell & 0xFF]
        base = m.day_index[cell >> 8]
        nd = self.nd
        occ = self.occ
        return all(not occ[r * nd + base] & em for r in L.resources)

    def blockers(self, sid: int, cell: int) -> list[int]:
        """Sesiones lectivas que ocupan profesores o clases de `sid` en `cell`."""
        m = self.m
        L = m.lessons[m.s_lesson[sid]]
        if L.duty:
            return []
        em = m.grids[L.grid].emask[cell & 0xFF]
        di = m.day_index[cell >> 8]
        nd = self.nd
        fuera: list[int] = []
        for r in L.resources:
            k = r * nd + di
            if self.occ[k] & em:
                for s2 in self.rd[k]:
                    if s2 == sid or s2 in fuera:
                        continue
                    L2 = m.lessons[m.s_lesson[s2]]
                    if m.grids[L2.grid].emask[self.cell[s2] & 0xFF] & em:
                        fuera.append(s2)
        return fuera

    # ------------------------------------------------------------------ #
    # Aulas
    # ------------------------------------------------------------------ #

    def pick_rooms(self, sid: int, cell: int) -> tuple[int, ...] | None:
        """Aulas para `sid` en `cell`: conserva las actuales o las de referencia
        si están libres; si no, la primera candidata libre. `None` si alguna
        línea que necesita aula no encuentra ninguna."""
        m = self.m
        L = m.lessons[m.s_lesson[sid]]
        if L.duty:
            # Las obligaciones no ocupan aula: se conservan las de referencia.
            return L.ref_rooms.get(cell, (-1,) * len(L.lines))
        if not L.needs_rooms:
            return (-1,) * len(L.lines)
        em = m.grids[L.grid].emask[cell & 0xFF]
        di = m.day_index[cell >> 8]
        nd = self.nd
        occ = self.occ
        bloqueos = m.room_blocks
        actuales = self.rooms[sid]
        ref = L.ref_rooms.get(cell)
        elegidas: list[int] = []
        for i, line in enumerate(L.lines):
            if not line.needs_room:
                elegidas.append(-1)
                continue
            elegida = -1
            for r in (actuales[i], ref[i] if ref is not None else -1, *line.candidates):
                if r < 0 or occ[r * nd + di] & em:
                    continue
                if bloqueos and (r, cell) in bloqueos:
                    continue
                elegida = r
                break
            if elegida < 0:
                return None
            elegidas.append(elegida)
        return tuple(elegidas)

    def rooms_free(self, sid: int, cell: int, rooms: tuple[int, ...]) -> bool:
        """`True` si esas aulas están libres (y no vetadas) en `cell`."""
        m = self.m
        L = m.lessons[m.s_lesson[sid]]
        if L.duty:
            return True
        em = m.grids[L.grid].emask[cell & 0xFF]
        di = m.day_index[cell >> 8]
        nd = self.nd
        for r in set(rooms):
            if r < 0:
                continue
            if self.occ[r * nd + di] & em:
                return False
            if m.room_blocks and (r, cell) in m.room_blocks:
                return False
        return True

    # ------------------------------------------------------------------ #
    # Colocar y quitar (sin puntuar)
    # ------------------------------------------------------------------ #

    def _add(self, sid: int, cell: int, rooms: tuple[int, ...]) -> None:
        m = self.m
        li = m.s_lesson[sid]
        L = m.lessons[li]
        self.cell[sid] = cell
        self.rooms[sid] = rooms
        self.n_unplaced -= 1
        self._dles.add(li)
        if L.duty:
            return
        nd = self.nd
        di = m.day_index[cell >> 8]
        em = m.grids[L.grid].emask[cell & 0xFF]
        occ = self.occ
        rd = self.rd
        for r in L.resources:
            k = r * nd + di
            occ[k] |= em
            rd[k].append(sid)
        for r in set(rooms):
            if r >= 0:
                k = r * nd + di
                occ[k] |= em
                rd[k].append(sid)
        ded = self._ded
        ed = self.ed
        for e in L.entities:
            k = e * nd + di
            ed[k].append(sid)
            ded.add(k)
        if self._wish_on and (L.wish_keys or m.wish_rooms):
            self._wish(L, cell, rooms, 1)

    def _remove(self, sid: int) -> None:
        m = self.m
        li = m.s_lesson[sid]
        L = m.lessons[li]
        cell = self.cell[sid]
        self.cell[sid] = -1
        self.n_unplaced += 1
        self._dles.add(li)
        if L.duty:
            return
        nd = self.nd
        di = m.day_index[cell >> 8]
        em = ~m.grids[L.grid].emask[cell & 0xFF]
        occ = self.occ
        rd = self.rd
        for r in L.resources:
            k = r * nd + di
            occ[k] &= em
            rd[k].remove(sid)
        rooms = self.rooms[sid]
        for r in set(rooms):
            if r >= 0:
                k = r * nd + di
                occ[k] &= em
                rd[k].remove(sid)
        ded = self._ded
        ed = self.ed
        for e in L.entities:
            k = e * nd + di
            ed[k].remove(sid)
            ded.add(k)
        if self._wish_on and (L.wish_keys or m.wish_rooms):
            self._wish(L, cell, rooms, -1)

    def _wish(self, L: LessonInfo, cell: int, rooms: tuple[int, ...], sign: int) -> None:
        """Ocupa (`sign=1`) o libera (`-1`) la celda para los deseos positivos."""
        m = self.m
        claves: tuple[int, ...] | list[int] = L.wish_keys
        if m.wish_rooms:
            aulas = [r for r in set(rooms) if r in m.wish_rooms]
            if aulas:
                claves = [*claves, *aulas]
        deseos = m.wishes
        busy = self.busy
        for k in claves:
            clave = (k, cell)
            deseo = deseos.get(clave)
            if deseo is None:
                continue
            antes = busy.get(clave, 0)
            busy[clave] = antes + sign
            if antes == 0 and sign > 0:
                tipo, valor = deseo
                self.wish_v[tipo] -= valor
                self.total -= self._w_wish[tipo] * valor
            elif antes == 1 and sign < 0:
                tipo, valor = deseo
                self.wish_v[tipo] += valor
                self.total += self._w_wish[tipo] * valor

    def _wish_total(self) -> int:
        """Puntos de los deseos positivos (ponderados) según `wish_v`."""
        return sum(w * v for w, v in zip(self._w_wish, self.wish_v, strict=True))

    def _fits_rooms(self, L: LessonInfo, cell: int, rooms: tuple[int, ...]) -> bool:
        m = self.m
        em = m.grids[L.grid].emask[cell & 0xFF]
        di = m.day_index[cell >> 8]
        nd = self.nd
        for r in rooms:
            if r >= 0:
                if self.occ[r * nd + di] & em:
                    return False
                if m.room_blocks and (r, cell) in m.room_blocks:
                    return False
        return True

    # ------------------------------------------------------------------ #
    # Movimiento con delta exacto
    # ------------------------------------------------------------------ #

    def apply(self, changes: Sequence[Change]) -> int | None:
        """Aplica los cambios y devuelve el delta del objetivo.

        Devuelve `None` (sin tocar nada) si algún cambio rompe una restricción
        dura. Tras un `apply` con éxito, `undo()` lo revierte exactamente.
        """
        m = self.m
        self._ded.clear()
        self._dles.clear()
        total0 = self.total
        extra0 = self.extra
        old: list[tuple[int, int, tuple[int, ...]]] = []
        for sid, _, _ in changes:
            c = self.cell[sid]
            old.append((sid, c, self.rooms[sid]))
            if c >= 0:
                self._remove(sid)
        new: list[tuple[int, int]] = []
        for sid, c, rooms in changes:
            if c < 0:
                continue
            L = m.lessons[m.s_lesson[sid]]
            ok = self.fits(sid, c)
            if ok:
                if rooms is None:
                    rooms = self.pick_rooms(sid, c)
                    ok = rooms is not None
                elif not L.duty:
                    ok = self._fits_rooms(L, c, rooms)
            if not ok or rooms is None:
                for s2, _ in reversed(new):
                    self._remove(s2)
                for s2, c2, r2 in old:
                    self.rooms[s2] = r2
                    if c2 >= 0:
                        self._add(s2, c2, r2)
                self.total = total0
                self.extra = extra0
                return None
            self._add(sid, c, rooms)
            new.append((sid, c))

        nd = self.nd
        delta = 0
        s_ed: list[tuple[int, int, tuple[int, ...], int]] = []
        ents: set[int] = set()
        for k in self._ded:
            s_ed.append((k, self.ed_val[k], self.ed_vec[k], self.ed_mask[k]))
            val, vec, mask = self._entity_day(k)
            delta += val - self.ed_val[k]
            self.ed_val[k] = val
            self.ed_vec[k] = vec
            self.ed_mask[k] = mask
            ents.add(k // nd)
        s_ew: list[tuple[int, int, tuple[int, ...]]] = []
        ent_week = self._ent_week
        for e in ents:
            if not ent_week[e]:
                continue
            s_ew.append((e, self.ew_val[e], self.ew_vec[e]))
            val, vec = self._week(e)
            delta += val - self.ew_val[e]
            self.ew_val[e] = val
            self.ew_vec[e] = vec
        s_les: list[tuple[int, int, tuple[int, ...], int]] = []
        dext = 0
        for li in self._dles:
            s_les.append((li, self.l_val[li], self.l_vec[li], self.l_ext[li]))
            val, vec, ext = self._lesson(li)
            delta += val - self.l_val[li]
            dext += ext - self.l_ext[li]
            self.l_val[li] = val
            self.l_vec[li] = vec
            self.l_ext[li] = ext
        self.total += delta
        self.extra += dext
        self._undo = Undo(old, new, s_ed, s_ew, s_les, total0, extra0)
        return self.total + self.extra - total0 - extra0

    def undo(self) -> None:
        """Revierte el último `apply` con éxito."""
        u = self._undo
        if u is None:
            raise RuntimeError("No hay movimiento que deshacer")
        self._undo = None
        for sid, _ in reversed(u.new):
            self._remove(sid)
        for sid, c, rooms in u.old:
            self.rooms[sid] = rooms
            if c >= 0:
                self._add(sid, c, rooms)
        for k, val, vec, mask in u.ed:
            self.ed_val[k] = val
            self.ed_vec[k] = vec
            self.ed_mask[k] = mask
        for e, val, vec in u.ew:
            self.ew_val[e] = val
            self.ew_vec[e] = vec
        for li, val, vec, ext in u.les:
            self.l_val[li] = val
            self.l_vec[li] = vec
            self.l_ext[li] = ext
        self.total = u.total
        self.extra = u.extra
        self._ded.clear()
        self._dles.clear()

    def last_undo(self) -> Undo:
        """Registro del último `apply` pendiente de confirmar o deshacer."""
        if self._undo is None:
            raise RuntimeError("No hay movimiento pendiente")
        return self._undo

    def commit(self) -> None:
        """Acepta el último movimiento (libera su registro de deshacer)."""
        self._undo = None

    # ------------------------------------------------------------------ #
    # Funciones locales (réplica literal de `untis_model.evaluation`)
    # ------------------------------------------------------------------ #

    def _entity_day(self, k: int) -> tuple[int, tuple[int, ...], int]:
        m = self.m
        e = k // self.nd
        ent = m.entities[e]
        sids = self.ed[k]
        is_class = ent.kind is EntityKind.CLASS
        if not sids:
            return 0, (_ZERO_CD if is_class else _ZERO_TD), 0
        g = ent.grid
        grids = m.grids
        lessons = m.lessons
        s_lesson = m.s_lesson
        cell = self.cell
        mask = 0
        for s in sids:
            mask |= grids[lessons[s_lesson[s]].grid].ovl[cell[s] & 0xFF][g]
        memo = self._memo[ent.profile]
        hit = memo.get(mask)
        if hit is None:
            prof = m.profiles[ent.profile]
            if is_class:
                vec = self._class_mask(prof, mask)
                hit = (sum(w * v for w, v in zip(self._w_cd, vec, strict=False)), vec)
            else:
                vec = self._teacher_mask(prof, mask)
                hit = (sum(w * v for w, v in zip(self._w_td, vec, strict=True)), vec)
            memo[mask] = hit
        if not is_class:
            return hit[0], hit[1], mask
        sval, svec = self._class_sessions(e, sids)
        if not sval and svec is _ZERO_CS:
            return hit[0], hit[1] + _ZERO_CS, mask
        return hit[0] + sval, hit[1] + svec, mask

    def _teacher_mask(self, prof: Profile, m: int) -> tuple[int, ...]:
        g = self.m.grids[prof.grid]
        n = m.bit_count()
        hg = gaps(m)
        gpd = excess(hg, prof.ntp_day_min, prof.ntp_day_max)
        ppd = excess(n, prof.ppd_min, prof.ppd_max)
        manana = (m & g.morning).bit_count()
        tarde = (m & g.afternoon).bit_count()
        suelto = (manana == 1) + (tarde == 1)
        seguidos = 0
        if prof.consecutive_max is not None:
            tope = prof.consecutive_max
            seguidos = sum(max(0, r - tope) for r in runs(m))
        almuerzo = 0
        if prof.lunch_min and manana and tarde:
            libres = (g.band & ~m).bit_count()
            if libres < prof.lunch_min:
                almuerzo = prof.lunch_min - libres
        aislada = 1 if tarde == 1 else 0
        return (hg, gpd, ppd, suelto, seguidos, almuerzo, aislada)

    def _class_mask(self, prof: Profile, m: int) -> tuple[int, ...]:
        g = self.m.grids[prof.grid]
        n = m.bit_count()
        hg = gaps(m)
        ppd = excess(n, prof.ppd_min, prof.ppd_max)
        manana = (m & g.morning).bit_count()
        tarde = (m & g.afternoon).bit_count()
        almuerzo = 0
        if prof.lunch_min and manana and tarde:
            libres = (g.band & ~m).bit_count()
            if libres < prof.lunch_min:
                almuerzo = prof.lunch_min - libres
        tarde_si = 1 if tarde else 0
        suelto = (manana == 1) + (tarde == 1)
        ultimo = 1 if m & g.last else 0
        return (hg, ppd, almuerzo, tarde_si, suelto, ultimo)

    def _class_sessions(self, e: int, sids: list[int]) -> tuple[int, tuple[int, ...]]:
        """Criterios de clase y día que dependen de la lista de sesiones."""
        m = self.m
        ent = m.entities[e]
        lessons = m.lessons
        s_lesson = m.s_lesson
        cell = self.cell
        principales = 0
        por_materia: dict[int, int] = {}
        repetida = False
        g = ent.grid
        grids = m.grids
        for s in sids:
            L = lessons[s_lesson[s]]
            if L.main:
                principales += 1
            ov = grids[L.grid].ovl[cell[s] & 0xFF][g]
            if L.subject in por_materia:
                repetida = True
                por_materia[L.subject] |= ov
            else:
                por_materia[L.subject] = ov
        mpd = 0
        if ent.main_per_day is not None and principales > ent.main_per_day:
            mpd = principales - ent.main_per_day
        dsd = 0
        if repetida:
            for mask in por_materia.values():
                tramos = count_runs(mask)
                if tramos > 1:
                    dsd += tramos - 1
        mnc = 0
        sgc = 0
        if (m.any_main or m.any_group) and len(sids) > 1:
            orden = sorted(
                (
                    grids[lessons[s_lesson[s]].grid].start[cell[s] & 0xFF],
                    lessons[s_lesson[s]].number,
                    cell[s] & 0xFF,
                    s,
                )
                for s in sids
            )
            for (_, a_num, _, a), (b_start, b_num, _, b) in pairwise(orden):
                La = lessons[s_lesson[a]]
                if a_num == b_num:
                    continue
                a_end = grids[La.grid].end[cell[a] & 0xFF]
                if b_start - a_end > 10:
                    continue
                Lb = lessons[s_lesson[b]]
                if La.main and Lb.main:
                    mnc += 1
                if La.group >= 0 and La.group == Lb.group and La.subject != Lb.subject:
                    sgc += 1
        seq = 0
        if m.any_sequence:
            for s in sids:
                L = lessons[s_lesson[s]]
                antes = L.sequence_after
                if antes < 0:
                    continue
                inicio = grids[L.grid].start[cell[s] & 0xFF]
                previas = [o for o in sids if lessons[s_lesson[o]].subject == antes]
                if previas and not any(
                    grids[lessons[s_lesson[o]].grid].start[cell[o] & 0xFF] < inicio for o in previas
                ):
                    seq += 1
        if not (mpd or mnc or sgc or dsd or seq):
            return 0, _ZERO_CS
        w = self._w_cd
        val = w[6] * mpd + w[7] * mnc + w[8] * sgc + w[9] * dsd + w[10] * seq
        return val, (mpd, mnc, sgc, dsd, seq)

    def _week(self, e: int) -> tuple[int, tuple[int, ...]]:
        m = self.m
        ent = m.entities[e]
        nd = self.nd
        base = e * nd
        ed = self.ed
        masks = self.ed_mask
        g = m.grids[ent.grid]
        unspec = 0
        for kind, count in ent.unspecified:
            libres = 0
            for d in g.days:
                k = base + m.day_index[d]
                mk = masks[k] if ed[k] else 0
                if kind is UnspecifiedKind.FREE_DAY:
                    libres += mk == 0
                elif kind is UnspecifiedKind.FREE_MORNING:
                    libres += not mk & g.morning
                else:
                    libres += not mk & g.afternoon
            if libres < count:
                unspec += count - libres
        if ent.kind is EntityKind.CLASS:
            if not unspec:
                return 0, _ZERO_CW
            return self._w_cw[0] * unspec, (unspec,)
        dias = 0
        huecos = 0
        cargas: list[int] = []
        for k in range(base, base + nd):
            if ed[k]:
                dias += 1
                mk = masks[k]
                huecos += gaps(mk)
                cargas.append(mk.bit_count())
        gpw = 0
        if ent.ntp_week is not None and dias:
            # El evaluador solo recorre profesores con alguna sesión.
            gpw = excess(huecos, ent.ntp_week.min, ent.ntp_week.max)
        dpw = 0
        if ent.days_per_week_max is not None and dias > ent.days_per_week_max:
            dpw = dias - ent.days_per_week_max
        lb = 0
        if len(cargas) >= 2:
            lb = max(0, max(cargas) - min(cargas) - 1)
        if not (gpw or dpw or lb or unspec):
            return 0, _ZERO_TW
        w = self._w_tw
        return w[0] * gpw + w[1] * dpw + w[2] * lb + w[3] * unspec, (gpw, dpw, lb, unspec)

    def _lesson(self, li: int) -> tuple[int, tuple[int, ...], int]:
        m = self.m
        L = m.lessons[li]
        cell = self.cell
        placed = [s for s in L.sids if cell[s] >= 0]
        n = len(placed)
        unpl = L.ppw - n
        penal = unpl * UNPLACED_PENALTY if unpl > 0 else 0
        if n == 0:
            return penal, _ZERO_L, 0
        g = m.grids[L.grid]
        pos = g.pos
        por_dia: dict[int, int] = {}
        periodos: dict[int, int] = {}
        for s in placed:
            c = cell[s]
            d = c >> 8
            p = c & 0xFF
            q = pos[p]
            por_dia[d] = por_dia.get(d, 0) | ((1 << q) if q >= 0 else 0)
            periodos[d] = periodos.get(d, 0) | (1 << p)
        dp = 0
        if L.dp_set:
            dobles = sum(r // 2 for mk in por_dia.values() for r in runs(mk))
            dp = excess(dobles, L.dp_min, L.dp_max)
        blk = 0
        if L.blocks:
            tramos = sorted((r for mk in por_dia.values() for r in runs(mk)), reverse=True)
            for b in L.blocks:
                if tramos and tramos[0] >= b:
                    tramos.pop(0)
                else:
                    blk += 1
        nsd = 0
        nsdc = 0
        if L.not_same_day:
            for mk in por_dia.values():
                t = count_runs(mk)
                if t > 1:
                    nsd += t - 1
            nsdc = sum(1 for d in por_dia if d + 1 in por_dia)
        uni = 0
        if L.ideal_days >= 0 and len(por_dia) < L.ideal_days:
            uni = L.ideal_days - len(por_dia)
        spc = 0
        for d, pm in periodos.items():
            siguiente = periodos.get(d + 1)
            if siguiente is not None:
                spc += (pm & siguiente).bit_count()
        topt = mm = trt = trc = trs = req = opt = cap = chain = trr = 0
        if not L.duty:
            topt = L.no_teacher * n
            if L.main:
                mm = sum(1 for s in placed if g.afternoon_period[cell[s] & 0xFF])
            if L.cell_costs:
                for s in placed:
                    a, b, c3 = L.cell_costs.get(cell[s], (0, 0, 0))
                    trt += a
                    trc += b
                    trs += c3
            if self._room_costs:
                for s in placed:
                    r1, r2, r3, r4 = self._room_cost(L, self.rooms[s])
                    req += r1
                    opt += r2
                    cap += r3
                    chain += r4
                    if m.room_requests:
                        trr += self._room_requests(self.rooms[s], cell[s])
        vec = (dp, blk, nsd, nsdc, uni, spc, topt, mm, trt, trc, trs, req, opt, cap, chain, trr)
        val = penal
        if dp or blk or nsd or nsdc or uni or spc or topt or mm or trt or trc or trs:
            w = self._w_l
            val += (
                w[0] * dp
                + w[1] * blk
                + w[2] * nsd
                + w[3] * nsdc
                + w[4] * uni
                + w[5] * spc
                + w[6] * topt
                + w[7] * mm
                + w[8] * trt
                + w[9] * trc
                + w[10] * trs
            )
        if req or opt or cap or chain or trr:
            w = self._w_l
            val += w[11] * req + w[12] * opt + w[13] * cap + w[14] * chain + w[15] * trr
        ext = 0
        if m.change_penalty:
            ext = m.change_penalty * sum(1 for s in placed if cell[s] not in L.ref_cells)
        return val, vec, ext

    def _room_cost(self, L: LessonInfo, rooms: tuple[int, ...]) -> tuple[int, int, int, int]:
        clave = (L.index, rooms)
        hit = self._room_memo.get(clave)
        if hit is not None:
            return hit
        req = opt = cap = chain = 0
        for i, line in enumerate(L.lines):
            real = rooms[i]
            if line.required >= 0 and real != line.required:
                req += 1
            if line.room >= 0:
                if real != line.room and real not in line.chain:
                    opt += 1
                if real in line.chain:
                    chain += line.chain.index(real) + 1
        if L.students:
            caps = self.m.room_capacity
            for r in {x for x in rooms if x >= 0}:
                c = caps.get(r)
                if c is not None and L.students > c:
                    cap += 1
        hit = (req, opt, cap, chain)
        self._room_memo[clave] = hit
        return hit

    def _room_requests(self, rooms: tuple[int, ...], cell: int) -> int:
        d = cell_day(cell)
        p = cell_period(cell)
        total = 0
        for r in {x for x in rooms if x >= 0}:
            for req in self.m.room_requests.get(r, ()):
                if req.covers(d, p):
                    total += -req.value
        return total

    # ------------------------------------------------------------------ #
    # Informes
    # ------------------------------------------------------------------ #

    def violations(self) -> dict[str, int]:
        """Violaciones por criterio, sumando todos los ámbitos cacheados."""
        cuenta = [0] * len(CRITERIA)
        m = self.m
        nd = self.nd
        idx_td = [CRIT_INDEX[c] for c in TEACHER_DAY]
        idx_cd = [CRIT_INDEX[c] for c in CLASS_DAY]
        idx_tw = [CRIT_INDEX[c] for c in TEACHER_WEEK]
        idx_cw = [CRIT_INDEX[c] for c in CLASS_WEEK]
        idx_l = [CRIT_INDEX[c] for c in LESSON_SCOPE]
        for k, vec in enumerate(self.ed_vec):
            idx = idx_cd if m.entities[k // nd].kind is EntityKind.CLASS else idx_td
            for i, v in zip(idx, vec, strict=True):
                cuenta[i] += v
        for e, vec in enumerate(self.ew_vec):
            idx = idx_cw if m.entities[e].kind is EntityKind.CLASS else idx_tw
            for i, v in zip(idx, vec, strict=True):
                cuenta[i] += v
        for vec in self.l_vec:
            for i, v in zip(idx_l, vec, strict=True):
                cuenta[i] += v
        for c, v in zip(WISH_CRITERIA, self.wish_v, strict=True):
            cuenta[CRIT_INDEX[c]] += v
        return dict(zip(CRITERIA, cuenta, strict=True))

    def unplaced_periods(self) -> int:
        """Períodos sin colocar, como `Evaluation.unplaced_periods`."""
        return self.unplaced_count()

    @property
    def evaluation_total(self) -> int:
        """Número de evaluación completo: alias de `total`.

        La heurística nunca crea choques de recurso ni ocupa celdas -3, y los
        deseos positivos son blandos (ya están en `total`).
        """
        return self.total

    def evaluation(self) -> Evaluation:
        """Evaluación según el estado incremental (sin choques, por construcción)."""
        v = self.violations()
        w = self.m.weighting
        return Evaluation(
            unplaced_periods=self.unplaced_count(),
            clashes=0,
            scores=tuple(CriterionScore(c, v[c], w.weight(c)) for c in CRITERIA),
        )

    def recompute_total(self) -> int:
        """Suma de todos los ámbitos cacheados (para verificar `total`)."""
        return sum(self.ed_val) + sum(self.ew_val) + sum(self.l_val) + self._wish_total()

    def snapshot(self) -> tuple[list[int], list[tuple[int, ...]]]:
        """Copia de celdas y aulas (para guardar el mejor horario)."""
        return self.cell[:], self.rooms[:]

    def to_timetable(self, timetable_id: str, name: str = "") -> Timetable:
        """El horario actual como `Timetable` de Untis."""
        m = self.m
        ids = m.resource_ids
        asignaciones: list[Assignment] = []
        for sid, c in enumerate(self.cell):
            if c < 0:
                continue
            L = m.lessons[m.s_lesson[sid]]
            rooms = self.rooms[sid]
            for i in range(len(L.lines)):
                r = rooms[i] if i < len(rooms) else -1
                asignaciones.append(
                    Assignment(
                        lesson_number=L.number,
                        line=i,
                        day=cell_day(c),
                        period=cell_period(c),
                        room=ids[r] if r >= 0 else None,
                        fixed=L.fixed,
                    )
                )
        asignaciones.sort(key=lambda a: (a.lesson_number, a.day, a.period, a.line))
        return Timetable(id=timetable_id, name=name, assignments=tuple(asignaciones))


def load(state: State, cells: Sequence[int], rooms: Sequence[tuple[int, ...]]) -> None:
    """Carga en `state` (vacío) un horario guardado con `snapshot`, sin comprobar."""
    changes: list[Change] = [(s, c, rooms[s]) for s, c in enumerate(cells) if c >= 0]
    for s, r in enumerate(rooms):
        state.rooms[s] = r
    if changes and state.apply(changes) is None:
        raise RuntimeError("El horario guardado no es factible")
    state.commit()
