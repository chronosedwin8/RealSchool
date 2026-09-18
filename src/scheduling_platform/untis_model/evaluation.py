"""Número de evaluación de un horario, criterio a criterio (ADR-035).

Es el **evaluador de referencia**: define qué significa cada deslizador de la
ponderación y cuántas violaciones produce un horario. Vive en el dominio (no
importa el motor) para que todos lo compartan:

- la ventana de Evaluación y el Diagnóstico muestran su desglose;
- la heurística optimiza versiones incrementales de estos mismos criterios, y
  un test exige que coincidan con este evaluador;
- `bridge` lo usa para puntuar lo que devuelve CP-SAT.

Unidades Untis: todo se cuenta en **períodos** de la rejilla, no en minutos.
Cada entidad se mira sobre su *rejilla propia* (la de la clase; la más usada
por el profesor) y una sesión ocupa todos los períodos de esa rejilla que solapa
en el reloj de pared, así un profesor que da clase en dos rejillas con horas
distintas se evalúa con coherencia.

Duras (se cuentan en `Evaluation.clashes`, no en los deslizadores): choques de
profesor, clase o aula entre lecciones distintas y celdas -3 ("imposible")
ocupadas. Ningún deseo positivo es duro: +3 significa "muy deseable" (ADR-039).

Deseos de tiempo blandos (`time_request_<tipo>`): un -2/-1 cuesta `|valor|` por
cada sesión lectiva de la entidad en una celda que cubre; un +1/+2/+3 cuesta
`valor` por cada celda que cubre y en la que la entidad queda libre. "Ocupada"
es la misma identidad de celda que usan los negativos: alguna sesión lectiva de
la entidad tiene `(día, período)` igual a la celda. Las celdas de un deseo
positivo se expanden (`día=None`, `período=None`) sobre el *dominio* de la
entidad: los días y los períodos **lectivos** (nunca recreos) de su rejilla
propia en profesores y clases; en aulas, la unión de todas las rejillas del
proyecto; en materias, la unión de las rejillas de las lecciones lectivas
activas cuya materia principal es esa. Sin dominio (p. ej. un profesor sin
clases lectivas) el deseo positivo no cuenta.
Las obligaciones no lectivas (lecciones sin alumnos) no son exclusivas: el
horario publicado por Untis las solapa con clases.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import pairwise

from .common import EntityKind, HalfDay
from .lessons import Lesson
from .project import UntisProject
from .requests import TimeRequest, UnspecifiedKind
from .time_grid import TimeGrid
from .timetable import CriterionScore, Evaluation, Timetable
from .weighting import Weighting

# --------------------------------------------------------------------------- #
# Estructuras
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Session:
    """Una sesión colocada: una celda de una lección, con todo su acople."""

    lesson: int
    day: int
    period: int
    start: int
    end: int
    subject: str
    teachers: tuple[str, ...]
    classes: tuple[str, ...]
    rooms: tuple[str, ...]
    room_by_line: tuple[str | None, ...]
    duty: bool

    def overlaps(self, other: Session) -> bool:
        return self.day == other.day and self.start < other.end and other.start < self.end


@dataclass(frozen=True, slots=True)
class Violation:
    """Una violación concreta, con el salto a la lección o la celda."""

    criterion: str
    amount: int
    message: str
    entity_kind: EntityKind | None = None
    entity_id: str = ""
    lesson: int | None = None
    day: int | None = None
    period: int | None = None


@dataclass(frozen=True, slots=True)
class Clash:
    """Choque duro: un recurso ocupado dos veces a la vez, o un deseo duro roto."""

    kind: str
    """`teacher`, `class`, `room` o `time_request`."""
    entity_id: str
    lessons: tuple[int, ...]
    day: int
    message: str


@dataclass(frozen=True, slots=True)
class Report:
    """Evaluación completa: número, choques y detalle por criterio."""

    evaluation: Evaluation
    clashes: tuple[Clash, ...] = field(default_factory=tuple)
    violations: tuple[Violation, ...] = field(default_factory=tuple)
    unplaced: tuple[tuple[int, int], ...] = field(default_factory=tuple)
    """`(lección, períodos sin colocar)`."""

    def of(self, criterion: str) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.criterion == criterion)


# --------------------------------------------------------------------------- #
# Contexto precalculado
# --------------------------------------------------------------------------- #


def _is_duty(lesson: Lesson) -> bool:
    return not any(line.classes or line.student_group for line in lesson.lines)


@dataclass(slots=True)
class _Day:
    """Ocupación de una entidad en un día, en períodos de su rejilla propia."""

    periods: set[int] = field(default_factory=set)
    sessions: list[Session] = field(default_factory=list)


class Evaluator:
    """Evalúa horarios de un proyecto. Precalcula índices una sola vez."""

    def __init__(self, project: UntisProject) -> None:
        self.project = project
        self.lessons = project.lesson_by_number
        self.grids = project.grid_by_id
        self.classes = project.class_by_id
        self.teachers = project.teacher_by_id
        self.rooms = project.room_by_id
        self.subjects = project.subject_by_id
        self.duty = {n for n, le in self.lessons.items() if _is_duty(le)}

        # Rejilla propia de cada clase y de cada profesor.
        self.class_grid: dict[str, TimeGrid] = {}
        for clase in project.classes:
            g = self.grids.get(clase.time_grid)
            if g is not None:
                self.class_grid[clase.id] = g
        uso: defaultdict[str, Counter[str]] = defaultdict(Counter)
        for le in project.lessons:
            if le.number in self.duty:
                continue
            for t in le.teachers:
                uso[t][le.time_grid] += le.periods_per_week
            for c in le.classes:
                if c not in self.class_grid:
                    uso[f"class:{c}"][le.time_grid] += le.periods_per_week
        self.teacher_grid: dict[str, TimeGrid] = {}
        for clave, conteo in uso.items():
            g = self.grids.get(conteo.most_common(1)[0][0])
            if g is None:
                continue
            if clave.startswith("class:"):
                self.class_grid.setdefault(clave[6:], g)
            else:
                self.teacher_grid[clave] = g

        self.requests: defaultdict[tuple[EntityKind, str], list[TimeRequest]] = defaultdict(list)
        for r in project.time_requests:
            self.requests[(r.entity_kind, r.entity_id)].append(r)

        # Deseos positivos expandidos sobre el dominio de cada entidad.
        self._subject_grids: defaultdict[str, set[str]] = defaultdict(set)
        for le in project.active_lessons:
            if le.number not in self.duty and le.time_grid in self.grids:
                self._subject_grids[le.subjects[0] if le.subjects else ""].add(le.time_grid)
        self.positive: dict[tuple[EntityKind, str], tuple[tuple[int, int, int], ...]] = {}
        for entidad, lista in self.requests.items():
            positivos = [r for r in lista if r.value > 0]
            if not positivos:
                continue
            dominio = sorted(self.wish_domain(*entidad))
            celdas = tuple((d, p, r.value) for r in positivos for d, p in dominio if r.covers(d, p))
            if celdas:
                self.positive[entidad] = celdas

    def wish_domain(self, kind: EntityKind, entity: str) -> set[tuple[int, int]]:
        """Celdas `(día, período lectivo)` sobre las que se expande un deseo positivo.

        Profesores y clases: su rejilla propia. Aulas: la unión de todas las
        rejillas. Materias: la unión de las rejillas de sus lecciones lectivas
        activas. Nunca incluye recreos.
        """
        rejillas: list[TimeGrid]
        if kind is EntityKind.TEACHER:
            g = self.teacher_grid.get(entity)
            rejillas = [g] if g is not None else []
        elif kind is EntityKind.CLASS:
            g = self.class_grid.get(entity)
            rejillas = [g] if g is not None else []
        elif kind is EntityKind.ROOM:
            rejillas = list(self.project.time_grids)
        else:
            rejillas = [self.grids[x] for x in sorted(self._subject_grids.get(entity, ()))]
        return {(d, p.number) for g in rejillas for d in g.days for p in g.teaching_periods}

    # --- sesiones ------------------------------------------------------------ #

    def sessions(self, timetable: Timetable) -> list[Session]:
        """Una `Session` por celda colocada de cada lección (línea 0 manda)."""
        por_celda: defaultdict[tuple[int, int, int], dict[int, str | None]] = defaultdict(dict)
        for a in timetable.assignments:
            por_celda[(a.lesson_number, a.day, a.period)][a.line] = a.room
        resultado: list[Session] = []
        for (numero, dia, periodo), lineas in sorted(por_celda.items()):
            le = self.lessons.get(numero)
            if le is None or le.ignore:
                continue
            grid = self.grids.get(le.time_grid)
            p = grid.period(periodo) if grid is not None else None
            if p is None:
                continue
            por_linea = tuple(lineas.get(i) for i in range(len(le.lines)))
            resultado.append(
                Session(
                    lesson=numero,
                    day=dia,
                    period=periodo,
                    start=p.start,
                    end=p.end,
                    subject=le.subjects[0] if le.subjects else "",
                    teachers=le.teachers,
                    classes=le.classes,
                    rooms=tuple(dict.fromkeys(r for r in por_linea if r is not None)),
                    room_by_line=por_linea,
                    duty=numero in self.duty,
                )
            )
        return resultado

    # --- API ------------------------------------------------------------------ #

    def report(self, timetable: Timetable, weighting: Weighting | None = None) -> Report:
        """Evaluación completa del horario."""
        w = weighting if weighting is not None else self.project.weighting
        sesiones = self.sessions(timetable)
        ctx = _Context(self, sesiones)
        choques = tuple(_clashes(ctx))
        sin_colocar = tuple(_unplaced(ctx))
        violaciones: list[Violation] = []
        for criterio in Weighting.criteria():
            funcion = CRITERIA.get(criterio)
            if funcion is not None:
                violaciones.extend(funcion(ctx))
        puntos: Counter[str] = Counter()
        for v in violaciones:
            puntos[v.criterion] += v.amount
        scores = tuple(
            CriterionScore(c, violations=puntos.get(c, 0), weight=w.weight(c))
            for c in Weighting.criteria()
        )
        evaluacion = Evaluation(
            unplaced_periods=sum(n for _, n in sin_colocar),
            clashes=len(choques),
            scores=scores,
        )
        return Report(evaluacion, choques, tuple(violaciones), sin_colocar)

    def evaluate(self, timetable: Timetable, weighting: Weighting | None = None) -> Evaluation:
        """Solo el número de evaluación y su desglose."""
        return self.report(timetable, weighting).evaluation


def evaluate(
    project: UntisProject, timetable: Timetable, weighting: Weighting | None = None
) -> Evaluation:
    """Atajo: evalúa un horario del proyecto."""
    return Evaluator(project).evaluate(timetable, weighting)


# --------------------------------------------------------------------------- #
# Contexto de una evaluación
# --------------------------------------------------------------------------- #


def _overlapping_periods(grid: TimeGrid, start: int, end: int) -> list[int]:
    return [p.number for p in grid.teaching_periods if p.start < end and start < p.end]


class _Context:
    """Vistas derivadas de las sesiones, calculadas una vez por evaluación."""

    def __init__(self, ev: Evaluator, sessions: list[Session]) -> None:
        self.ev = ev
        self.sessions = sessions
        self.lective = [s for s in sessions if not s.duty]
        self.teacher_days: defaultdict[str, defaultdict[int, _Day]] = defaultdict(
            lambda: defaultdict(_Day)
        )
        self.class_days: defaultdict[str, defaultdict[int, _Day]] = defaultdict(
            lambda: defaultdict(_Day)
        )
        for s in self.lective:
            for t in s.teachers:
                g = ev.teacher_grid.get(t)
                if g is None:
                    continue
                dia = self.teacher_days[t][s.day]
                dia.periods.update(_overlapping_periods(g, s.start, s.end))
                dia.sessions.append(s)
            for c in s.classes:
                g = ev.class_grid.get(c)
                if g is None:
                    continue
                dia = self.class_days[c][s.day]
                dia.periods.update(_overlapping_periods(g, s.start, s.end))
                dia.sessions.append(s)
        self.by_lesson: defaultdict[int, list[Session]] = defaultdict(list)
        for s in sessions:
            self.by_lesson[s.lesson].append(s)

    def grid_of(self, kind: EntityKind, entity: str) -> TimeGrid | None:
        if kind is EntityKind.TEACHER:
            return self.ev.teacher_grid.get(entity)
        return self.ev.class_grid.get(entity)


# --------------------------------------------------------------------------- #
# Duras y no colocados
# --------------------------------------------------------------------------- #


def _clashes(ctx: _Context) -> Iterator[Clash]:
    """Choques de recurso entre lecciones distintas y deseos duros rotos."""
    for kind, atributo in (("teacher", "teachers"), ("class", "classes"), ("room", "rooms")):
        por_recurso: defaultdict[str, list[Session]] = defaultdict(list)
        for s in ctx.lective:
            for r in getattr(s, atributo):
                por_recurso[r].append(s)
        for recurso, lista in sorted(por_recurso.items()):
            lista.sort(key=lambda s: (s.day, s.start, s.lesson))
            vistos: set[frozenset[int]] = set()
            for i, a in enumerate(lista):
                for b in lista[i + 1 :]:
                    if b.day != a.day or b.start >= a.end:
                        break
                    par = frozenset({a.lesson, b.lesson})
                    if a.lesson == b.lesson or par in vistos:
                        continue
                    vistos.add(par)
                    yield Clash(
                        kind,
                        recurso,
                        tuple(sorted(par)),
                        a.day,
                        f"{kind} {recurso!r} en las lecciones {a.lesson} y {b.lesson} "
                        f"a la vez (día {a.day}).",
                    )

    for s in ctx.lective:
        for kind, ids in (
            (EntityKind.TEACHER, s.teachers),
            (EntityKind.CLASS, s.classes),
            (EntityKind.ROOM, s.rooms),
            (EntityKind.SUBJECT, (s.subject,)),
        ):
            for eid in ids:
                for r in ctx.ev.requests.get((kind, eid), ()):
                    if r.is_block and r.covers(s.day, s.period):
                        yield Clash(
                            "time_request",
                            eid,
                            (s.lesson,),
                            s.day,
                            f"La lección {s.lesson} ocupa una celda imposible (-3) de "
                            f"{kind.value} {eid!r} (día {s.day}, período {s.period}).",
                        )


def _unplaced(ctx: _Context) -> Iterator[tuple[int, int]]:
    colocadas = Counter(s.lesson for s in ctx.sessions)
    for le in ctx.ev.project.active_lessons:
        falta = le.periods_per_week - colocadas.get(le.number, 0)
        if falta > 0:
            yield (le.number, falta)


# --------------------------------------------------------------------------- #
# Utilidades de criterios
# --------------------------------------------------------------------------- #


def _gaps(grid: TimeGrid, periods: set[int]) -> int:
    """Períodos lectivos libres entre el primero y el último ocupados."""
    if len(periods) < 2:
        return 0
    lo, hi = min(periods), max(periods)
    return sum(1 for p in grid.teaching_periods if lo < p.number < hi and p.number not in periods)


def _runs(periods: set[int], grid: TimeGrid) -> list[list[int]]:
    """Tramos de períodos lectivos consecutivos ocupados."""
    orden = [p.number for p in grid.teaching_periods]
    tramos: list[list[int]] = []
    actual: list[int] = []
    for n in orden:
        if n in periods:
            actual.append(n)
        elif actual:
            tramos.append(actual)
            actual = []
    if actual:
        tramos.append(actual)
    return tramos


def _half(grid: TimeGrid, number: int) -> HalfDay:
    p = grid.period(number)
    return p.half_day if p is not None else HalfDay.MORNING


def _minmax_excess(value: int, lo: int | None, hi: int | None) -> int:
    exceso = 0
    if hi is not None and value > hi:
        exceso += value - hi
    if lo is not None and value < lo:
        exceso += lo - value
    return exceso


def _v(
    criterion: str,
    amount: int,
    message: str,
    *,
    entity_kind: EntityKind | None = None,
    entity_id: str = "",
    lesson: int | None = None,
    day: int | None = None,
    period: int | None = None,
) -> Violation:
    return Violation(criterion, amount, message, entity_kind, entity_id, lesson, day, period)


Criterion = Callable[[_Context], Iterator[Violation]]


# --------------------------------------------------------------------------- #
# Profesores 1
# --------------------------------------------------------------------------- #


def _teacher_gaps(ctx: _Context) -> Iterator[Violation]:
    for t, dias in sorted(ctx.teacher_days.items()):
        g = ctx.ev.teacher_grid[t]
        for d, dia in sorted(dias.items()):
            n = _gaps(g, dia.periods)
            if n:
                yield _v(
                    "teacher_gaps",
                    n,
                    f"{n} hueco(s) de {t!r} el día {d}.",
                    entity_kind=EntityKind.TEACHER,
                    entity_id=t,
                    day=d,
                )


def _teacher_gaps_per_day(ctx: _Context) -> Iterator[Violation]:
    for t, dias in sorted(ctx.teacher_days.items()):
        rango = ctx.ev.teachers[t].ntp_per_day if t in ctx.ev.teachers else None
        if rango is None or not rango.is_set:
            continue
        g = ctx.ev.teacher_grid[t]
        for d, dia in sorted(dias.items()):
            exceso = _minmax_excess(_gaps(g, dia.periods), rango.min, rango.max)
            if exceso:
                yield _v(
                    "teacher_gaps_per_day_max",
                    exceso,
                    f"Huecos de {t!r} el día {d} fuera de {rango.min}-{rango.max}.",
                    entity_kind=EntityKind.TEACHER,
                    entity_id=t,
                    day=d,
                )


def _teacher_gaps_per_week(ctx: _Context) -> Iterator[Violation]:
    for t, dias in sorted(ctx.teacher_days.items()):
        rango = ctx.ev.teachers[t].ntp_per_week if t in ctx.ev.teachers else None
        if rango is None or not rango.is_set:
            continue
        g = ctx.ev.teacher_grid[t]
        total = sum(_gaps(g, dia.periods) for dia in dias.values())
        exceso = _minmax_excess(total, rango.min, rango.max)
        if exceso:
            yield _v(
                "teacher_gaps_per_week_max",
                exceso,
                f"{t!r} suma {total} huecos semanales, fuera de {rango.min}-{rango.max}.",
                entity_kind=EntityKind.TEACHER,
                entity_id=t,
            )


def _teacher_periods_per_day(ctx: _Context) -> Iterator[Violation]:
    for t, dias in sorted(ctx.teacher_days.items()):
        rango = ctx.ev.teachers[t].periods_per_day if t in ctx.ev.teachers else None
        if rango is None or not rango.is_set:
            continue
        for d, dia in sorted(dias.items()):
            exceso = _minmax_excess(len(dia.periods), rango.min, rango.max)
            if exceso:
                yield _v(
                    "teacher_periods_per_day",
                    exceso,
                    f"{t!r} da {len(dia.periods)} períodos el día {d}, fuera de "
                    f"{rango.min}-{rango.max}.",
                    entity_kind=EntityKind.TEACHER,
                    entity_id=t,
                    day=d,
                )


def _teacher_days_per_week(ctx: _Context) -> Iterator[Violation]:
    for t, dias in sorted(ctx.teacher_days.items()):
        tope = ctx.ev.teachers[t].days_per_week_max if t in ctx.ev.teachers else None
        if tope is not None and len(dias) > tope:
            yield _v(
                "teacher_days_per_week_max",
                len(dias) - tope,
                f"{t!r} trabaja {len(dias)} días (máx. {tope}).",
                entity_kind=EntityKind.TEACHER,
                entity_id=t,
            )


def _teacher_single_half_day(ctx: _Context) -> Iterator[Violation]:
    for t, dias in sorted(ctx.teacher_days.items()):
        g = ctx.ev.teacher_grid[t]
        for d, dia in sorted(dias.items()):
            por_media = Counter(_half(g, p) for p in dia.periods)
            for media, n in sorted(por_media.items()):
                if n == 1:
                    yield _v(
                        "teacher_single_period_half_day",
                        1,
                        f"{t!r} tiene un solo período en la {media.value} del día {d}.",
                        entity_kind=EntityKind.TEACHER,
                        entity_id=t,
                        day=d,
                    )


# --------------------------------------------------------------------------- #
# Profesores 2
# --------------------------------------------------------------------------- #


def _teacher_consecutive(ctx: _Context) -> Iterator[Violation]:
    for t, dias in sorted(ctx.teacher_days.items()):
        tope = ctx.ev.teachers[t].consecutive_max if t in ctx.ev.teachers else None
        if tope is None:
            continue
        g = ctx.ev.teacher_grid[t]
        for d, dia in sorted(dias.items()):
            exceso = sum(max(0, len(r) - tope) for r in _runs(dia.periods, g))
            if exceso:
                yield _v(
                    "teacher_consecutive_max",
                    exceso,
                    f"{t!r} supera {tope} períodos seguidos el día {d}.",
                    entity_kind=EntityKind.TEACHER,
                    entity_id=t,
                    day=d,
                )


def _midday_band(grid: TimeGrid) -> set[int]:
    """Último período de la mañana y primero de la tarde: franja de almuerzo."""
    manana = [p.number for p in grid.teaching_periods if p.half_day is HalfDay.MORNING]
    tarde = [p.number for p in grid.teaching_periods if p.half_day is HalfDay.AFTERNOON]
    banda: set[int] = set()
    if manana:
        banda.add(manana[-1])
    if tarde:
        banda.add(tarde[0])
    return banda


def _lunch(
    ctx: _Context,
    criterion: str,
    kind: EntityKind,
    days: dict[str, defaultdict[int, _Day]],
    minimo_de: Callable[[str], int | None],
) -> Iterator[Violation]:
    for e, dias in sorted(days.items()):
        minimo = minimo_de(e)
        if not minimo:
            continue
        g = ctx.grid_of(kind, e)
        if g is None:
            continue
        banda = _midday_band(g)
        for d, dia in sorted(dias.items()):
            medias = {_half(g, p) for p in dia.periods}
            if len(medias) < 2:
                continue  # no trabaja mañana y tarde: no necesita almuerzo
            libres = len(banda - dia.periods)
            if libres < minimo:
                yield _v(
                    criterion,
                    minimo - libres,
                    f"{kind.value} {e!r} sin almuerzo suficiente el día {d}.",
                    entity_kind=kind,
                    entity_id=e,
                    day=d,
                )


def _teacher_lunch(ctx: _Context) -> Iterator[Violation]:
    def minimo(t: str) -> int | None:
        return ctx.ev.teachers[t].lunch_break.min if t in ctx.ev.teachers else None

    return _lunch(ctx, "teacher_lunch_break", EntityKind.TEACHER, ctx.teacher_days, minimo)


def _teacher_isolated_afternoon(ctx: _Context) -> Iterator[Violation]:
    for t, dias in sorted(ctx.teacher_days.items()):
        g = ctx.ev.teacher_grid[t]
        for d, dia in sorted(dias.items()):
            tarde = [p for p in dia.periods if _half(g, p) is HalfDay.AFTERNOON]
            if len(tarde) == 1:
                yield _v(
                    "teacher_isolated_afternoon",
                    1,
                    f"{t!r} viene por la tarde del día {d} para un solo período.",
                    entity_kind=EntityKind.TEACHER,
                    entity_id=t,
                    day=d,
                )


def _teacher_load_balance(ctx: _Context) -> Iterator[Violation]:
    for t, dias in sorted(ctx.teacher_days.items()):
        cargas = [len(dia.periods) for dia in dias.values()]
        if len(cargas) < 2:
            continue
        desequilibrio = max(cargas) - min(cargas) - 1
        if desequilibrio > 0:
            yield _v(
                "teacher_load_balance",
                desequilibrio,
                f"Carga diaria de {t!r} desigual ({min(cargas)}-{max(cargas)} períodos).",
                entity_kind=EntityKind.TEACHER,
                entity_id=t,
            )


def _teacher_optimization(ctx: _Context) -> Iterator[Violation]:
    for s in ctx.lective:
        le = ctx.ev.lessons[s.lesson]
        sin = sum(1 for line in le.lines if line.teacher is None)
        if sin:
            yield _v(
                "teacher_optimization",
                sin,
                f"La lección {s.lesson} tiene {sin} línea(s) sin profesor (día {s.day}).",
                lesson=s.lesson,
                day=s.day,
                period=s.period,
            )


# --------------------------------------------------------------------------- #
# Clases
# --------------------------------------------------------------------------- #


def _class_gaps(ctx: _Context) -> Iterator[Violation]:
    for c, dias in sorted(ctx.class_days.items()):
        g = ctx.ev.class_grid[c]
        for d, dia in sorted(dias.items()):
            n = _gaps(g, dia.periods)
            if n:
                yield _v(
                    "class_gaps",
                    n,
                    f"{n} hueco(s) de la clase {c!r} el día {d}.",
                    entity_kind=EntityKind.CLASS,
                    entity_id=c,
                    day=d,
                )


def _class_periods_per_day(ctx: _Context) -> Iterator[Violation]:
    for c, dias in sorted(ctx.class_days.items()):
        rango = ctx.ev.classes[c].periods_per_day if c in ctx.ev.classes else None
        if rango is None or not rango.is_set:
            continue
        for d, dia in sorted(dias.items()):
            exceso = _minmax_excess(len(dia.periods), rango.min, rango.max)
            if exceso:
                yield _v(
                    "class_periods_per_day",
                    exceso,
                    f"La clase {c!r} tiene {len(dia.periods)} períodos el día {d}, fuera de "
                    f"{rango.min}-{rango.max}.",
                    entity_kind=EntityKind.CLASS,
                    entity_id=c,
                    day=d,
                )


def _class_lunch(ctx: _Context) -> Iterator[Violation]:
    def minimo(c: str) -> int | None:
        return ctx.ev.classes[c].lunch_break.min if c in ctx.ev.classes else None

    return _lunch(ctx, "class_lunch_break", EntityKind.CLASS, ctx.class_days, minimo)


def _class_afternoons(ctx: _Context) -> Iterator[Violation]:
    for c, dias in sorted(ctx.class_days.items()):
        g = ctx.ev.class_grid[c]
        for d, dia in sorted(dias.items()):
            if any(_half(g, p) is HalfDay.AFTERNOON for p in dia.periods):
                yield _v(
                    "class_afternoon_periods",
                    1,
                    f"La clase {c!r} tiene clase la tarde del día {d}.",
                    entity_kind=EntityKind.CLASS,
                    entity_id=c,
                    day=d,
                )


def _class_single_periods(ctx: _Context) -> Iterator[Violation]:
    for c, dias in sorted(ctx.class_days.items()):
        g = ctx.ev.class_grid[c]
        for d, dia in sorted(dias.items()):
            por_media = Counter(_half(g, p) for p in dia.periods)
            for media, n in sorted(por_media.items()):
                if n == 1:
                    yield _v(
                        "class_single_periods",
                        1,
                        f"La clase {c!r} tiene un solo período en la {media.value} del día {d}.",
                        entity_kind=EntityKind.CLASS,
                        entity_id=c,
                        day=d,
                    )


# --------------------------------------------------------------------------- #
# Materias
# --------------------------------------------------------------------------- #


def _lesson_runs(ctx: _Context, lesson: int) -> dict[int, list[list[int]]]:
    """Tramos consecutivos de una lección por día, en períodos de su rejilla."""
    le = ctx.ev.lessons[lesson]
    grid = ctx.ev.grids.get(le.time_grid)
    if grid is None:
        return {}
    por_dia: defaultdict[int, set[int]] = defaultdict(set)
    for s in ctx.by_lesson.get(lesson, ()):
        por_dia[s.day].add(s.period)
    return {d: _runs(ps, grid) for d, ps in por_dia.items()}


def _subject_double_periods(ctx: _Context) -> Iterator[Violation]:
    for numero in sorted(ctx.by_lesson):
        le = ctx.ev.lessons[numero]
        rango = le.double_periods
        if not rango.is_set:
            continue
        dobles = sum(len(r) // 2 for tramos in _lesson_runs(ctx, numero).values() for r in tramos)
        exceso = _minmax_excess(dobles, rango.min, rango.max)
        if exceso:
            yield _v(
                "subject_double_periods",
                exceso,
                f"La lección {numero} tiene {dobles} doble(s), se piden {rango.min}-{rango.max}.",
                lesson=numero,
            )


def _subject_blocks(ctx: _Context) -> Iterator[Violation]:
    for numero in sorted(ctx.by_lesson):
        le = ctx.ev.lessons[numero]
        largos = [b for b in le.block if b >= 3]
        if not largos:
            continue
        tramos = sorted(
            (len(r) for ts in _lesson_runs(ctx, numero).values() for r in ts), reverse=True
        )
        faltan = 0
        for b in sorted(largos, reverse=True):
            if tramos and tramos[0] >= b:
                tramos.pop(0)
            else:
                faltan += 1
        if faltan:
            yield _v(
                "subject_blocks",
                faltan,
                f"La lección {numero} no logra {faltan} bloque(s) de {largos}.",
                lesson=numero,
            )


def _not_same_day(ctx: _Context, le: Lesson) -> bool:
    if le.not_same_day:
        return True
    return any(
        ctx.ev.subjects[line.subject].not_same_day
        for line in le.lines
        if line.subject in ctx.ev.subjects
    )


def _subject_not_same_day(ctx: _Context) -> Iterator[Violation]:
    for numero in sorted(ctx.by_lesson):
        le = ctx.ev.lessons[numero]
        if not _not_same_day(ctx, le):
            continue
        for d, tramos in sorted(_lesson_runs(ctx, numero).items()):
            if len(tramos) > 1:
                yield _v(
                    "subject_not_same_day",
                    len(tramos) - 1,
                    f"La lección {numero} aparece {len(tramos)} veces el día {d}.",
                    lesson=numero,
                    day=d,
                )


def _subject_not_consecutive_days(ctx: _Context) -> Iterator[Violation]:
    for numero in sorted(ctx.by_lesson):
        le = ctx.ev.lessons[numero]
        if not _not_same_day(ctx, le):
            continue
        dias = sorted({s.day for s in ctx.by_lesson[numero]})
        seguidos = sum(1 for a, b in pairwise(dias) if b == a + 1)
        if seguidos:
            yield _v(
                "subject_not_consecutive_days",
                seguidos,
                f"La lección {numero} cae en días seguidos {seguidos} vez/veces.",
                lesson=numero,
            )


def _subject_sequence(ctx: _Context) -> Iterator[Violation]:
    for numero in sorted(ctx.by_lesson):
        le = ctx.ev.lessons[numero]
        antes = le.sequence_after
        if antes is None:
            continue
        for s in ctx.by_lesson[numero]:
            for c in s.classes:
                dia = ctx.class_days[c].get(s.day) if c in ctx.class_days else None
                if dia is None:
                    continue
                previas = [o for o in dia.sessions if o.subject == antes]
                if previas and not any(o.start < s.start for o in previas):
                    yield _v(
                        "subject_sequence",
                        1,
                        f"La lección {numero} va antes que {antes!r} el día {s.day} (clase {c!r}).",
                        lesson=numero,
                        day=s.day,
                        period=s.period,
                    )


def _subject_required_room(ctx: _Context) -> Iterator[Violation]:
    for s in ctx.lective:
        le = ctx.ev.lessons[s.lesson]
        for i, line in enumerate(le.lines):
            materia = ctx.ev.subjects.get(line.subject)
            exigida = materia.required_room if materia is not None else None
            if exigida is None:
                continue
            real = s.room_by_line[i] if i < len(s.room_by_line) else None
            if real != exigida:
                yield _v(
                    "subject_required_room",
                    1,
                    f"La lección {s.lesson}, línea {i}, debe ir en {exigida!r} (está en {real!r}).",
                    lesson=s.lesson,
                    day=s.day,
                    period=s.period,
                )


# --------------------------------------------------------------------------- #
# Materias principales
# --------------------------------------------------------------------------- #


def _is_main(ctx: _Context, s: Session) -> bool:
    m = ctx.ev.subjects.get(s.subject)
    return m is not None and m.main_subject


def _main_per_day(ctx: _Context) -> Iterator[Violation]:
    for c, dias in sorted(ctx.class_days.items()):
        tope = ctx.ev.classes[c].main_subjects_per_day if c in ctx.ev.classes else None
        if tope is None:
            continue
        for d, dia in sorted(dias.items()):
            n = sum(1 for s in dia.sessions if _is_main(ctx, s))
            if n > tope:
                yield _v(
                    "main_subject_per_day_max",
                    n - tope,
                    f"La clase {c!r} tiene {n} períodos de materias principales el día {d} "
                    f"(máx. {tope}).",
                    entity_kind=EntityKind.CLASS,
                    entity_id=c,
                    day=d,
                )


def _adjacent_pairs(ctx: _Context) -> Iterator[tuple[str, int, Session, Session]]:
    """Pares de sesiones consecutivas (sin hueco) de cada clase y día."""
    for c, dias in sorted(ctx.class_days.items()):
        for d, dia in sorted(dias.items()):
            orden = sorted(dia.sessions, key=lambda s: s.start)
            for a, b in pairwise(orden):
                if a.lesson != b.lesson and b.start - a.end <= 10:
                    yield c, d, a, b


def _main_not_consecutive(ctx: _Context) -> Iterator[Violation]:
    for c, d, a, b in _adjacent_pairs(ctx):
        if _is_main(ctx, a) and _is_main(ctx, b):
            yield _v(
                "main_subject_not_consecutive",
                1,
                f"La clase {c!r} tiene dos materias principales seguidas el día {d}.",
                entity_kind=EntityKind.CLASS,
                entity_id=c,
                day=d,
                period=b.period,
            )


def _main_morning(ctx: _Context) -> Iterator[Violation]:
    for s in ctx.lective:
        if not _is_main(ctx, s):
            continue
        grid = ctx.ev.grids.get(ctx.ev.lessons[s.lesson].time_grid)
        if grid is not None and _half(grid, s.period) is HalfDay.AFTERNOON:
            yield _v(
                "main_subject_morning",
                1,
                f"La materia principal de la lección {s.lesson} cae por la tarde.",
                lesson=s.lesson,
                day=s.day,
                period=s.period,
            )


def _subject_group_not_consecutive(ctx: _Context) -> Iterator[Violation]:
    for c, d, a, b in _adjacent_pairs(ctx):
        ma, mb = ctx.ev.subjects.get(a.subject), ctx.ev.subjects.get(b.subject)
        if (
            ma is not None
            and mb is not None
            and ma.subject_group is not None
            and ma.subject_group == mb.subject_group
            and a.subject != b.subject
        ):
            yield _v(
                "subject_group_not_consecutive",
                1,
                f"La clase {c!r} tiene seguidas dos materias del grupo "
                f"{ma.subject_group!r} el día {d}.",
                entity_kind=EntityKind.CLASS,
                entity_id=c,
                day=d,
                period=b.period,
            )


# --------------------------------------------------------------------------- #
# Aulas
# --------------------------------------------------------------------------- #


def _chain(ctx: _Context, room: str) -> list[str]:
    cadena: list[str] = []
    actual = ctx.ev.rooms[room].alternative_room if room in ctx.ev.rooms else None
    while actual is not None and actual not in cadena and actual != room:
        cadena.append(actual)
        actual = ctx.ev.rooms[actual].alternative_room if actual in ctx.ev.rooms else None
    return cadena


def _room_optimization(ctx: _Context) -> Iterator[Violation]:
    for s in ctx.lective:
        le = ctx.ev.lessons[s.lesson]
        for i, line in enumerate(le.lines):
            if line.room is None:
                continue
            real = s.room_by_line[i] if i < len(s.room_by_line) else None
            if real != line.room and real not in _chain(ctx, line.room):
                yield _v(
                    "room_optimization",
                    1,
                    f"La lección {s.lesson}, línea {i}, pidió {line.room!r} y está en {real!r}.",
                    lesson=s.lesson,
                    day=s.day,
                    period=s.period,
                )


def _room_capacity(ctx: _Context) -> Iterator[Violation]:
    for s in ctx.lective:
        alumnos = sum(ctx.ev.classes[c].students for c in s.classes if c in ctx.ev.classes)
        if not alumnos:
            continue
        for r in s.rooms:
            aula = ctx.ev.rooms.get(r)
            if aula is not None and aula.capacity is not None and alumnos > aula.capacity:
                yield _v(
                    "room_capacity",
                    1,
                    f"{alumnos} alumnos de la lección {s.lesson} no caben en {r!r} "
                    f"(capacidad {aula.capacity}).",
                    entity_kind=EntityKind.ROOM,
                    entity_id=r,
                    lesson=s.lesson,
                    day=s.day,
                    period=s.period,
                )


def _room_alternative_chain(ctx: _Context) -> Iterator[Violation]:
    for s in ctx.lective:
        le = ctx.ev.lessons[s.lesson]
        for i, line in enumerate(le.lines):
            if line.room is None:
                continue
            real = s.room_by_line[i] if i < len(s.room_by_line) else None
            cadena = _chain(ctx, line.room)
            if real in cadena:
                salto = cadena.index(real) + 1
                yield _v(
                    "room_alternative_chain",
                    salto,
                    f"La lección {s.lesson}, línea {i}, usa la alternativa nº {salto} ({real!r}).",
                    lesson=s.lesson,
                    day=s.day,
                    period=s.period,
                )


# --------------------------------------------------------------------------- #
# Distribución de períodos
# --------------------------------------------------------------------------- #


def _distribution_same_day(ctx: _Context) -> Iterator[Violation]:
    """Misma materia en tramos separados el mismo día, para la misma clase."""
    for c, dias in sorted(ctx.class_days.items()):
        g = ctx.ev.class_grid[c]
        for d, dia in sorted(dias.items()):
            por_materia: defaultdict[str, set[int]] = defaultdict(set)
            for s in dia.sessions:
                por_materia[s.subject].update(_overlapping_periods(g, s.start, s.end))
            for materia, periodos in sorted(por_materia.items()):
                tramos = len(_runs(periodos, g))
                if tramos > 1:
                    yield _v(
                        "distribution_same_day",
                        tramos - 1,
                        f"La clase {c!r} tiene {materia!r} en {tramos} tramos el día {d}.",
                        entity_kind=EntityKind.CLASS,
                        entity_id=c,
                        day=d,
                    )


def _distribution_uniform(ctx: _Context) -> Iterator[Violation]:
    for numero in sorted(ctx.by_lesson):
        le = ctx.ev.lessons[numero]
        grid = ctx.ev.grids.get(le.time_grid)
        if grid is None:
            continue
        dobles = le.double_periods.min or 0
        ideal = min(le.periods_per_week - dobles, len(grid.days))
        usados = len({s.day for s in ctx.by_lesson[numero]})
        if usados < ideal:
            yield _v(
                "distribution_uniform_week",
                ideal - usados,
                f"La lección {numero} ocupa {usados} días; podría repartirse en {ideal}.",
                lesson=numero,
            )


def _distribution_same_period(ctx: _Context) -> Iterator[Violation]:
    for numero in sorted(ctx.by_lesson):
        por_dia: defaultdict[int, set[int]] = defaultdict(set)
        for s in ctx.by_lesson[numero]:
            por_dia[s.day].add(s.period)
        repetidos = sum(
            len(por_dia[d] & por_dia[d + 1]) for d in sorted(por_dia) if d + 1 in por_dia
        )
        if repetidos:
            yield _v(
                "distribution_same_period_consecutive_days",
                repetidos,
                f"La lección {numero} repite período en días seguidos {repetidos} vez/veces.",
                lesson=numero,
            )


def _distribution_first_last(ctx: _Context) -> Iterator[Violation]:
    """Clases en el último período lectivo de su rejilla."""
    for c, dias in sorted(ctx.class_days.items()):
        g = ctx.ev.class_grid[c]
        lectivos = g.teaching_periods
        if not lectivos:
            continue
        ultimo = lectivos[-1].number
        for d, dia in sorted(dias.items()):
            if ultimo in dia.periods:
                yield _v(
                    "distribution_first_last_period",
                    1,
                    f"La clase {c!r} tiene clase en el último período del día {d}.",
                    entity_kind=EntityKind.CLASS,
                    entity_id=c,
                    day=d,
                    period=ultimo,
                )


# --------------------------------------------------------------------------- #
# Deseos de tiempo
# --------------------------------------------------------------------------- #


def _ids_of(s: Session, kind: EntityKind) -> tuple[str, ...]:
    if kind is EntityKind.TEACHER:
        return s.teachers
    if kind is EntityKind.CLASS:
        return s.classes
    if kind is EntityKind.ROOM:
        return s.rooms
    return (s.subject,)


def _requests_of(ctx: _Context, kind: EntityKind, criterion: str) -> Iterator[Violation]:
    """Deseos blandos: -2/-1 en celdas ocupadas y +1/+2/+3 en celdas libres."""
    ocupadas: defaultdict[str, set[tuple[int, int]]] = defaultdict(set)
    for s in ctx.lective:
        for eid in _ids_of(s, kind):
            ocupadas[eid].add((s.day, s.period))
            for r in ctx.ev.requests.get((kind, eid), ()):
                if -3 < r.value < 0 and r.covers(s.day, s.period):
                    yield _v(
                        criterion,
                        -r.value,
                        f"La lección {s.lesson} ocupa una celda no deseada ({r.value}) de "
                        f"{kind.value} {eid!r}.",
                        entity_kind=kind,
                        entity_id=eid,
                        lesson=s.lesson,
                        day=s.day,
                        period=s.period,
                    )
    for (k, eid), celdas in sorted(ctx.ev.positive.items()):
        if k is not kind:
            continue
        propias = ocupadas.get(eid, set())
        for d, p, valor in celdas:
            if (d, p) not in propias:
                yield _v(
                    criterion,
                    valor,
                    f"{kind.value} {eid!r} prefiere tener clase aquí (+{valor}) y está libre "
                    f"(día {d}, período {p}).",
                    entity_kind=kind,
                    entity_id=eid,
                    day=d,
                    period=p,
                )


def _req_teacher(ctx: _Context) -> Iterator[Violation]:
    return _requests_of(ctx, EntityKind.TEACHER, "time_request_teacher")


def _req_class(ctx: _Context) -> Iterator[Violation]:
    return _requests_of(ctx, EntityKind.CLASS, "time_request_class")


def _req_room(ctx: _Context) -> Iterator[Violation]:
    return _requests_of(ctx, EntityKind.ROOM, "time_request_room")


def _req_subject(ctx: _Context) -> Iterator[Violation]:
    return _requests_of(ctx, EntityKind.SUBJECT, "time_request_subject")


def _req_unspecified(ctx: _Context) -> Iterator[Violation]:
    for u in ctx.ev.project.unspecified_requests:
        dias: dict[int, _Day]
        if u.entity_kind is EntityKind.TEACHER:
            dias = dict(ctx.teacher_days.get(u.entity_id, {}))
        elif u.entity_kind is EntityKind.CLASS:
            dias = dict(ctx.class_days.get(u.entity_id, {}))
        else:
            continue
        g = ctx.grid_of(u.entity_kind, u.entity_id)
        if g is None:
            continue
        if u.kind is UnspecifiedKind.FREE_DAY:
            libres = sum(1 for d in g.days if not dias.get(d, _Day()).periods)
        else:
            media = HalfDay.MORNING if u.kind is UnspecifiedKind.FREE_MORNING else HalfDay.AFTERNOON
            libres = sum(
                1
                for d in g.days
                if not any(_half(g, p) is media for p in dias.get(d, _Day()).periods)
            )
        if libres < u.count:
            yield _v(
                "time_request_unspecified",
                u.count - libres,
                f"{u.entity_kind.value} {u.entity_id!r} pide {u.count} "
                f"{u.kind.value} y tiene {libres}.",
                entity_kind=u.entity_kind,
                entity_id=u.entity_id,
            )


#: Criterio -> función que produce sus violaciones.
CRITERIA: dict[str, Criterion] = {
    "teacher_gaps": _teacher_gaps,
    "teacher_gaps_per_day_max": _teacher_gaps_per_day,
    "teacher_gaps_per_week_max": _teacher_gaps_per_week,
    "teacher_periods_per_day": _teacher_periods_per_day,
    "teacher_days_per_week_max": _teacher_days_per_week,
    "teacher_single_period_half_day": _teacher_single_half_day,
    "teacher_consecutive_max": _teacher_consecutive,
    "teacher_lunch_break": _teacher_lunch,
    "teacher_isolated_afternoon": _teacher_isolated_afternoon,
    "teacher_load_balance": _teacher_load_balance,
    "teacher_optimization": _teacher_optimization,
    "class_gaps": _class_gaps,
    "class_periods_per_day": _class_periods_per_day,
    "class_lunch_break": _class_lunch,
    "class_afternoon_periods": _class_afternoons,
    "class_single_periods": _class_single_periods,
    "subject_double_periods": _subject_double_periods,
    "subject_blocks": _subject_blocks,
    "subject_not_same_day": _subject_not_same_day,
    "subject_not_consecutive_days": _subject_not_consecutive_days,
    "subject_sequence": _subject_sequence,
    "subject_required_room": _subject_required_room,
    "main_subject_per_day_max": _main_per_day,
    "main_subject_not_consecutive": _main_not_consecutive,
    "main_subject_morning": _main_morning,
    "subject_group_not_consecutive": _subject_group_not_consecutive,
    "room_optimization": _room_optimization,
    "room_capacity": _room_capacity,
    "room_alternative_chain": _room_alternative_chain,
    "distribution_same_day": _distribution_same_day,
    "distribution_uniform_week": _distribution_uniform,
    "distribution_same_period_consecutive_days": _distribution_same_period,
    "distribution_first_last_period": _distribution_first_last,
    "time_request_teacher": _req_teacher,
    "time_request_class": _req_class,
    "time_request_room": _req_room,
    "time_request_subject": _req_subject,
    "time_request_unspecified": _req_unspecified,
}


__all__ = [
    "CRITERIA",
    "Clash",
    "Evaluator",
    "Report",
    "Session",
    "Violation",
    "evaluate",
]
