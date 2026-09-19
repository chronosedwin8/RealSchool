"""Reparto de guardias de recreo (Pausenaufsichten), como lo hace Untis.

Entra un proyecto con sus **turnos** (`Supervision`: zona, día y recreo) y sale
el mismo conjunto de turnos con profesor donde se ha podido. Es algoritmo puro:
solo depende de `untis_model`, no del motor, y con la misma `seed` da siempre el
mismo reparto.

Reglas (las de Untis, sección "Aufsichten"):

1. Un profesor solo vigila un recreo si **ese día está en el colegio**: da clase
   en la hora inmediatamente anterior o en la inmediatamente posterior al
   recreo, según el horario que se pase. Sin horario no hay candidatos.
2. Nadie hace dos turnos en el mismo recreo del mismo día (aunque sean zonas
   distintas).
3. Se respeta `Teacher.supervision_max`, en minutos de guardia a la semana:
   `None` es sin límite y `0` deja al profesor fuera del reparto.
4. Los turnos con `fixed=True` no se tocan; los que tienen profesor pero no
   están fijados vuelven al reparto (regenerar es volver a repartir).

Algoritmo, en dos partes:

- **Voraz**: los turnos se atienden de menos candidatos a más (el difícil
  primero) y, a igualdad, por peso de zona; cada uno va al candidato con menos
  minutos acumulados, prefiriendo a quien da clase a los dos lados del recreo.
- **Mejora local**: pasadas de (a) relleno con expulsión -un turno sin cubrir
  toma a un profesor al que se le mueve otro turno a un compañero-, (b)
  reasignaciones y (c) intercambios entre dos turnos; se acepta lo que baja el
  coste. El orden de exploración de cada pasada lo baraja un `random.Random`
  sembrado con `seed`, así que el resultado es determinista.

El coste que se minimiza es ``suma(minutos_del_profesor**2)``, que es lo que
reparte parejo, más `SINGLE_SIDE_COST` por cada turno cubierto por alguien que
solo está a un lado del recreo (desempate: cualquier mejora real del equilibrio
pesa más que esa preferencia).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from scheduling_platform.untis_model.project import UntisProject
from scheduling_platform.untis_model.supervision import Supervision, SupervisionArea
from scheduling_platform.untis_model.time_grid import TimeGrid
from scheduling_platform.untis_model.timetable import Timetable

#: Coste de dar un turno a quien solo da clase a un lado del recreo.
SINGLE_SIDE_COST = 50
#: Pasadas de mejora local como máximo (cada una recorre todos los turnos).
MAX_PASSES = 20


# --------------------------------------------------------------------------- #
# Resultado
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SupervisionOutcome:
    """Lo que devuelve un reparto de guardias."""

    supervisions: tuple[Supervision, ...]
    """Todos los turnos del proyecto, en su orden original, ya repartidos."""
    uncovered: int
    """Cuántos se quedaron sin profesor."""
    minutes_by_teacher: dict[str, int] = field(default_factory=dict)
    """Minutos de guardia de cada profesor con al menos un turno."""
    elapsed: float = 0.0
    """Segundos empleados."""

    @property
    def total(self) -> int:
        """Turnos que había que cubrir."""
        return len(self.supervisions)

    @property
    def assigned(self) -> int:
        """Turnos con profesor."""
        return sum(1 for s in self.supervisions if s.assigned)

    @property
    def spread(self) -> int:
        """Diferencia de minutos entre quien más vigila y quien menos."""
        if not self.minutes_by_teacher:
            return 0
        valores = self.minutes_by_teacher.values()
        return max(valores) - min(valores)


# --------------------------------------------------------------------------- #
# Preparación
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Shift:
    """Un turno listo para repartir: sus minutos y quién puede cubrirlo."""

    index: int
    """Posición en `project.supervisions`."""
    slot: tuple[int, int]
    """Celda `(día, recreo)`."""
    minutes: int
    weight: int
    candidates: tuple[str, ...]
    both_sides: frozenset[str]
    """Candidatos que dan clase antes **y** después del recreo."""


def grid_of_area(project: UntisProject, area: SupervisionArea | None) -> TimeGrid | None:
    """Rejilla cuyos recreos vigila la zona (vacío = la primera del proyecto)."""
    if area is None:
        return None
    if area.time_grid:
        return project.grid_by_id.get(area.time_grid)
    return project.time_grids[0] if project.time_grids else None


def supervision_minutes(grid: TimeGrid | None, supervision: Supervision) -> int:
    """Minutos que dura el turno: los suyos o, si son 0, los del recreo."""
    if supervision.minutes:
        return supervision.minutes
    periodo = grid.period(supervision.period) if grid is not None else None
    return periodo.duration if periodo is not None else 0


def neighbour_periods(grid: TimeGrid, period: int) -> tuple[int | None, int | None]:
    """Horas lectivas inmediatamente anterior y posterior a ese recreo."""
    lectivas = [p.number for p in grid.teaching_periods]
    antes = [n for n in lectivas if n < period]
    despues = [n for n in lectivas if n > period]
    return (max(antes) if antes else None, min(despues) if despues else None)


def teacher_slots(
    project: UntisProject, timetable: Timetable | None
) -> dict[str, set[tuple[int, int]]]:
    """Celdas `(día, hora)` en las que cada profesor da clase en ese horario."""
    ocupacion: dict[str, set[tuple[int, int]]] = {}
    if timetable is None:
        return ocupacion
    lecciones = project.lesson_by_number
    for a in timetable.assignments:
        leccion = lecciones.get(a.lesson_number)
        if leccion is None:
            continue
        for linea in leccion.lines:
            if linea.teacher:
                ocupacion.setdefault(linea.teacher, set()).add(a.slot)
    return ocupacion


def _reference_timetable(project: UntisProject, timetable: Timetable | None) -> Timetable | None:
    """El horario que se pasa o, si no, el primero del proyecto."""
    if timetable is not None:
        return timetable
    return project.timetables[0] if project.timetables else None


def _build_shifts(project: UntisProject, timetable: Timetable | None) -> tuple[_Shift, ...]:
    """Turnos con sus minutos y sus candidatos, en el orden del proyecto."""
    zonas = project.area_by_id
    ocupacion = teacher_slots(project, timetable)
    profesores = [t for t in project.teachers if t.supervision_max != 0]
    turnos: list[_Shift] = []
    for i, s in enumerate(project.supervisions):
        zona = zonas.get(s.area)
        grid = grid_of_area(project, zona)
        minutos = supervision_minutes(grid, s)
        antes, despues = neighbour_periods(grid, s.period) if grid is not None else (None, None)
        candidatos: list[str] = []
        ambos: set[str] = set()
        for t in profesores:
            celdas = ocupacion.get(t.id, set())
            de_antes = antes is not None and (s.day, antes) in celdas
            de_despues = despues is not None and (s.day, despues) in celdas
            if de_antes or de_despues:
                candidatos.append(t.id)
                if de_antes and de_despues:
                    ambos.add(t.id)
        turnos.append(
            _Shift(
                index=i,
                slot=s.slot,
                minutes=minutos,
                weight=zona.weight if zona is not None else 0,
                candidates=tuple(candidatos),
                both_sides=frozenset(ambos),
            )
        )
    return tuple(turnos)


# --------------------------------------------------------------------------- #
# Estado del reparto
# --------------------------------------------------------------------------- #


class _Plan:
    """Reparto en curso: quién cubre cada turno, con su coste al día."""

    def __init__(self, project: UntisProject, shifts: tuple[_Shift, ...]) -> None:
        self.shifts = shifts
        self.teacher_of: list[str] = [""] * len(shifts)
        self.minutes: dict[str, int] = {}
        self.limit: dict[str, int | None] = {
            t.id: t.supervision_max for t in project.teachers if t.supervision_max != 0
        }
        self.busy: dict[tuple[int, int], set[str]] = {}
        self._squares = 0
        self._singles = 0

    # --- consulta ---------------------------------------------------------- #

    @property
    def cost(self) -> int:
        """Lo que se minimiza: equilibrio de minutos y preferencia de cercanía."""
        return self._squares + SINGLE_SIDE_COST * self._singles

    def can_take(self, teacher: str, shift: _Shift) -> bool:
        """`True` si ese profesor puede cubrir el turno ahora mismo."""
        if teacher in self.busy.get(shift.slot, set()):
            return False
        tope = self.limit.get(teacher)
        return tope is None or self.minutes.get(teacher, 0) + shift.minutes <= tope

    def uncovered(self) -> list[int]:
        return [i for i, t in enumerate(self.teacher_of) if not t]

    # --- mutación ----------------------------------------------------------- #

    def place(self, index: int, teacher: str) -> None:
        turno = self.shifts[index]
        previos = self.minutes.get(teacher, 0)
        self.minutes[teacher] = previos + turno.minutes
        self._squares += (previos + turno.minutes) ** 2 - previos**2
        self._singles += 0 if teacher in turno.both_sides else 1
        self.busy.setdefault(turno.slot, set()).add(teacher)
        self.teacher_of[index] = teacher

    def clear(self, index: int) -> str:
        """Deja el turno sin profesor y devuelve quién lo tenía."""
        teacher = self.teacher_of[index]
        if not teacher:
            return ""
        turno = self.shifts[index]
        previos = self.minutes[teacher]
        self.minutes[teacher] = previos - turno.minutes
        self._squares += (previos - turno.minutes) ** 2 - previos**2
        self._singles -= 0 if teacher in turno.both_sides else 1
        self.busy[turno.slot].discard(teacher)
        self.teacher_of[index] = ""
        return teacher

    def final_minutes(self) -> dict[str, int]:
        """Minutos por profesor, solo los que acabaron con algún turno."""
        return {t: m for t, m in sorted(self.minutes.items()) if m > 0}


# --------------------------------------------------------------------------- #
# Fases
# --------------------------------------------------------------------------- #


def _greedy(plan: _Plan, pending: list[int]) -> None:
    """Fase voraz: el turno más difícil primero, al candidato con menos minutos."""
    orden = sorted(
        pending,
        key=lambda i: (
            len(plan.shifts[i].candidates),
            -plan.shifts[i].weight,
            plan.shifts[i].slot,
            i,
        ),
    )
    for i in orden:
        turno = plan.shifts[i]
        posibles = [t for t in turno.candidates if plan.can_take(t, turno)]
        if not posibles:
            continue
        mejor = min(
            posibles,
            key=lambda t: (plan.minutes.get(t, 0), 0 if t in turno.both_sides else 1, t),
        )
        plan.place(i, mejor)


def _fill_uncovered(plan: _Plan, movibles: frozenset[int], order: list[int]) -> bool:
    """Cubre turnos vacíos, si hace falta moviendo otro turno del candidato."""
    mejoro = False
    for i in order:
        if plan.teacher_of[i]:
            continue
        turno = plan.shifts[i]
        for t in turno.candidates:
            if plan.can_take(t, turno):
                plan.place(i, t)
                mejoro = True
                break
            if _eject(plan, movibles, i, t):
                mejoro = True
                break
    return mejoro


def _eject(plan: _Plan, movibles: frozenset[int], index: int, teacher: str) -> bool:
    """Libera al profesor pasando uno de sus turnos a otro, y le da `index`."""
    turno = plan.shifts[index]
    suyos = sorted(j for j in movibles if plan.teacher_of[j] == teacher)
    for j in suyos:
        otro = plan.shifts[j]
        anterior = plan.clear(j)
        for t2 in otro.candidates:
            if t2 != teacher and plan.can_take(t2, otro):
                plan.place(j, t2)
                if plan.can_take(teacher, turno):
                    plan.place(index, teacher)
                    return True
                plan.clear(j)
                break
        plan.place(j, anterior)
    return False


def _rebalance(plan: _Plan, movibles: frozenset[int], order: list[int]) -> bool:
    """Reasigna turnos sueltos mientras baje el coste."""
    mejoro = False
    for i in order:
        if i not in movibles or not plan.teacher_of[i]:
            continue
        turno = plan.shifts[i]
        antes = plan.cost
        actual = plan.clear(i)
        mejor, mejor_coste = actual, antes
        for t in turno.candidates:
            if not plan.can_take(t, turno):
                continue
            plan.place(i, t)
            if plan.cost < mejor_coste:
                mejor, mejor_coste = t, plan.cost
            plan.clear(i)
        plan.place(i, mejor)
        mejoro = mejoro or mejor_coste < antes
    return mejoro


def _swaps(plan: _Plan, movibles: frozenset[int], order: list[int]) -> bool:
    """Intercambia los profesores de dos turnos si con eso baja el coste."""
    mejoro = False
    sueltos = [i for i in order if i in movibles and plan.teacher_of[i]]
    for pos, i in enumerate(sueltos):
        for j in sueltos[pos + 1 :]:
            ti, tj = plan.teacher_of[i], plan.teacher_of[j]
            if ti == tj or not ti or not tj:
                continue
            if tj not in plan.shifts[i].candidates or ti not in plan.shifts[j].candidates:
                continue
            antes = plan.cost
            plan.clear(i)
            plan.clear(j)
            if plan.can_take(tj, plan.shifts[i]) and plan.can_take(ti, plan.shifts[j]):
                plan.place(i, tj)
                plan.place(j, ti)
                if plan.cost < antes:
                    mejoro = True
                    continue
                plan.clear(i)
                plan.clear(j)
            plan.place(i, ti)
            plan.place(j, tj)
    return mejoro


# --------------------------------------------------------------------------- #
# Punto de entrada
# --------------------------------------------------------------------------- #


def assign_supervisions(
    project: UntisProject,
    timetable: Timetable | None = None,
    *,
    seed: int = 0,
    should_stop: Callable[[], bool] | None = None,
) -> SupervisionOutcome:
    """Reparte los turnos de guardia sin profesor sobre el horario indicado.

    `timetable` es el horario del que se saca quién está en el colegio a cada
    hora; si no se pasa, se usa el primero del proyecto. Los turnos fijados no
    se tocan y los demás se reparten desde cero. Nunca lanza: si nadie puede
    cubrir un turno, se queda sin cubrir y se cuenta en el resultado.
    """
    t0 = time.perf_counter()
    horario = _reference_timetable(project, timetable)
    turnos = _build_shifts(project, horario)
    plan = _Plan(project, turnos)
    # Fijado sin profesor no conserva nada: entra en el reparto como cualquier otro.
    fijos = {i for i, s in enumerate(project.supervisions) if s.fixed and s.teacher}
    for i in sorted(fijos):
        plan.place(i, project.supervisions[i].teacher)
    movibles = frozenset(i for i in range(len(turnos)) if i not in fijos)
    _greedy(plan, sorted(movibles))

    rng = random.Random(seed)
    for _ in range(MAX_PASSES):
        if should_stop is not None and should_stop():
            break
        orden = list(range(len(turnos)))
        rng.shuffle(orden)
        mejoro = _fill_uncovered(plan, movibles, orden)
        mejoro = _rebalance(plan, movibles, orden) or mejoro
        mejoro = _swaps(plan, movibles, orden) or mejoro
        if not mejoro:
            break

    repartidos = tuple(
        s if i in fijos else _with_teacher(s, plan.teacher_of[i])
        for i, s in enumerate(project.supervisions)
    )
    return SupervisionOutcome(
        supervisions=repartidos,
        uncovered=sum(1 for s in repartidos if not s.assigned),
        minutes_by_teacher=plan.final_minutes(),
        elapsed=time.perf_counter() - t0,
    )


def _with_teacher(supervision: Supervision, teacher: str) -> Supervision:
    """Copia del turno con ese profesor (o sin ninguno si va vacío)."""
    if supervision.teacher == teacher:
        return supervision
    return Supervision(
        area=supervision.area,
        day=supervision.day,
        period=supervision.period,
        teacher=teacher,
        fixed=supervision.fixed,
        minutes=supervision.minutes,
    )
