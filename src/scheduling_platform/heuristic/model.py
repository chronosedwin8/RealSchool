"""Representación interna compacta de un proyecto para la heurística.

Se construye **una vez** a partir de un `UntisProject` y traduce todo a
enteros y listas planas, que es lo que Python recorre deprisa:

- una **celda** es `día << 8 | período` (el período en la rejilla de la
  lección);
- los choques se miden en el **reloj de pared**: cada `(rejilla, período)`
  ocupa un conjunto de *intervalos elementales* (los tramos entre todas las
  fronteras de período de todas las rejillas), guardado como máscara de bits;
  dos sesiones chocan si sus máscaras se cortan el mismo día;
- cada profesor y cada clase con rejilla propia es una **entidad** evaluada
  sobre esa rejilla, como en `untis_model.evaluation`: una sesión le marca los
  períodos lectivos de su rejilla que solapa (otra máscara de bits).

Las sesiones y sus celdas admitidas salen de `untis_model.sessions`, la misma
definición que usa el puente hacia CP-SAT: un horario de la heurística siempre
se puede traducir al modelo canónico.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Final

from scheduling_platform.untis_model.common import EntityKind, HalfDay, MinMax
from scheduling_platform.untis_model.evaluation import Evaluator
from scheduling_platform.untis_model.lessons import Lesson
from scheduling_platform.untis_model.project import UntisProject
from scheduling_platform.untis_model.requests import TimeRequest, UnspecifiedKind
from scheduling_platform.untis_model.sessions import (
    all_session_durations,
    cells_by_duration,
    reference_cells,
)
from scheduling_platform.untis_model.time_grid import TimeGrid
from scheduling_platform.untis_model.timetable import Timetable
from scheduling_platform.untis_model.weighting import UNPLACED_PENALTY, Weighting

#: Criterios en el orden canónico de la ponderación.
CRITERIA: Final[tuple[str, ...]] = Weighting.criteria()
CRIT_INDEX: Final[dict[str, int]] = {c: i for i, c in enumerate(CRITERIA)}

#: Criterios de cada ámbito local; cada ámbito cachea un vector alineado con su tupla.
TEACHER_DAY: Final = (
    "teacher_gaps",
    "teacher_gaps_per_day_max",
    "teacher_periods_per_day",
    "teacher_single_period_half_day",
    "teacher_consecutive_max",
    "teacher_lunch_break",
    "teacher_isolated_afternoon",
)
TEACHER_WEEK: Final = (
    "teacher_gaps_per_week_max",
    "teacher_days_per_week_max",
    "teacher_load_balance",
    "time_request_unspecified",
)
CLASS_DAY: Final = (
    "class_gaps",
    "class_periods_per_day",
    "class_lunch_break",
    "class_afternoon_periods",
    "class_single_periods",
    "distribution_first_last_period",
    "main_subject_per_day_max",
    "main_subject_not_consecutive",
    "subject_group_not_consecutive",
    "distribution_same_day",
    "subject_sequence",
)
CLASS_WEEK: Final = ("time_request_unspecified",)
LESSON_SCOPE: Final = (
    "subject_double_periods",
    "subject_blocks",
    "subject_not_same_day",
    "subject_not_consecutive_days",
    "distribution_uniform_week",
    "distribution_same_period_consecutive_days",
    "teacher_optimization",
    "main_subject_morning",
    "time_request_teacher",
    "time_request_class",
    "time_request_subject",
    "subject_required_room",
    "room_optimization",
    "room_capacity",
    "room_alternative_chain",
    "time_request_room",
)

#: Penalización interna por deseo +3 incumplido. No entra en el número de
#: evaluación (el evaluador lo cuenta como choque), pero la heurística lo evita.
MANDATORY_PENALTY: Final = UNPLACED_PENALTY // 10

#: Aulas candidatas como máximo por línea.
MAX_ROOM_CANDIDATES: Final = 12


def cell_code(day: int, period: int) -> int:
    """Codifica la celda `(día, período)` en un entero."""
    return day << 8 | period


def cell_day(cell: int) -> int:
    """Día de una celda codificada."""
    return cell >> 8


def cell_period(cell: int) -> int:
    """Período de una celda codificada."""
    return cell & 0xFF


def is_duty(lesson: Lesson) -> bool:
    """Obligación no lectiva: ninguna línea tiene clases ni grupo de alumnos."""
    return not any(line.classes or line.student_group for line in lesson.lines)


# --------------------------------------------------------------------------- #
# Rejillas
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class GridInfo:
    """Una rejilla vista como máscaras de bits sobre sus períodos lectivos."""

    index: int
    grid: TimeGrid
    days: tuple[int, ...]
    teaching: tuple[int, ...]
    """Números de período lectivo en orden; la posición en la tupla es el bit."""
    morning: int
    afternoon: int
    band: int
    """Franja de almuerzo: último lectivo de la mañana y primero de la tarde."""
    last: int
    """Bit del último período lectivo (0 si no hay)."""
    size: int
    """Mayor número de período definido + 1 (longitud de las tablas)."""
    start: list[int]
    end: list[int]
    emask: list[int]
    """Intervalos elementales del reloj que ocupa cada período."""
    ovl: list[tuple[int, ...]]
    """`ovl[período][rejilla]`: períodos lectivos de otra rejilla que solapa."""
    pos: list[int]
    """Posición lectiva de cada número de período (-1 si no es lectivo)."""
    afternoon_period: list[bool]
    """`_half(grid, período) is AFTERNOON`, para cualquier período definido."""


def _build_grids(project: UntisProject) -> list[GridInfo]:
    grids = project.time_grids
    fronteras = sorted({t for g in grids for p in g.periods for t in (p.start, p.end)})
    tramos = list(pairwise(fronteras))

    def mascara_reloj(start: int, end: int) -> int:
        m = 0
        for i, (a, b) in enumerate(tramos):
            if a >= start and b <= end:
                m |= 1 << i
        return m

    infos: list[GridInfo] = []
    for gi, g in enumerate(grids):
        lectivos = g.teaching_periods
        manana = 0
        tarde = 0
        for i, p in enumerate(lectivos):
            if p.half_day is HalfDay.AFTERNOON:
                tarde |= 1 << i
            else:
                manana |= 1 << i
        m_pos = [i for i, p in enumerate(lectivos) if p.half_day is HalfDay.MORNING]
        t_pos = [i for i, p in enumerate(lectivos) if p.half_day is HalfDay.AFTERNOON]
        banda = (1 << m_pos[-1] if m_pos else 0) | (1 << t_pos[0] if t_pos else 0)
        size = max((p.number for p in g.periods), default=0) + 1
        start = [0] * size
        end = [0] * size
        emask = [0] * size
        pos = [-1] * size
        tarde_p = [False] * size
        for p in g.periods:
            start[p.number] = p.start
            end[p.number] = p.end
            emask[p.number] = mascara_reloj(p.start, p.end)
            tarde_p[p.number] = p.half_day is HalfDay.AFTERNOON
        for i, p in enumerate(lectivos):
            pos[p.number] = i
        infos.append(
            GridInfo(
                index=gi,
                grid=g,
                days=tuple(g.days),
                teaching=tuple(p.number for p in lectivos),
                morning=manana,
                afternoon=tarde,
                band=banda,
                last=(1 << (len(lectivos) - 1)) if lectivos else 0,
                size=size,
                start=start,
                end=end,
                emask=emask,
                ovl=[],
                pos=pos,
                afternoon_period=tarde_p,
            )
        )
    # Solape de cada período con los períodos lectivos de cada rejilla.
    for info in infos:
        filas: list[tuple[int, ...]] = []
        for n in range(info.size):
            per = info.grid.period(n) if n else None
            if per is None:
                filas.append(tuple(0 for _ in infos))
                continue
            fila: list[int] = []
            for otra in infos:
                m = 0
                for i, q in enumerate(otra.grid.teaching_periods):
                    if q.start < per.end and per.start < q.end:
                        m |= 1 << i
                fila.append(m)
            filas.append(tuple(fila))
        info.ovl = filas
    return infos


# --------------------------------------------------------------------------- #
# Entidades (profesores y clases con rejilla propia)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Profile:
    """Parámetros de los que depende la puntuación de un día de una entidad.

    Entidades con el mismo perfil comparten la memoización por máscara.
    """

    is_class: bool
    grid: int
    ppd_min: int | None = None
    ppd_max: int | None = None
    ntp_day_min: int | None = None
    ntp_day_max: int | None = None
    consecutive_max: int | None = None
    lunch_min: int | None = None


@dataclass(slots=True)
class Entity:
    """Profesor o clase evaluado día a día sobre su rejilla propia."""

    index: int
    kind: EntityKind
    id: str
    grid: int
    profile: int
    resource: int
    ntp_week: MinMax | None = None
    days_per_week_max: int | None = None
    main_per_day: int | None = None
    unspecified: tuple[tuple[UnspecifiedKind, int], ...] = ()


# --------------------------------------------------------------------------- #
# Lecciones y sesiones
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class LineInfo:
    """Una línea del acople, vista desde la elección de aula."""

    needs_room: bool
    candidates: tuple[int, ...]
    """Aulas candidatas (ids de recurso) en orden de preferencia."""
    room: int
    """Aula pedida por la línea (-1 si ninguna)."""
    chain: tuple[int, ...]
    """Cadena de aulas alternativas de `room`."""
    required: int
    """Aula exigida por la materia de la línea (-1 si ninguna)."""


@dataclass(slots=True)
class LessonInfo:
    """Datos estáticos de una lección para la evaluación incremental."""

    index: int
    number: int
    lesson: Lesson
    grid: int
    """Índice de rejilla (-1 si la rejilla no existe)."""
    duty: bool
    fixed: bool
    ppw: int
    sids: tuple[int, ...]
    resources: tuple[int, ...]
    """Profesores y clases (ids de recurso) que ocupa cada sesión lectiva."""
    entities: tuple[int, ...]
    """Entidades evaluadas (profesores y clases con rejilla) de la lección."""
    subject: int
    main: bool
    group: int
    sequence_after: int
    no_teacher: int
    """Líneas sin profesor (criterio `teacher_optimization`)."""
    dp_min: int | None
    dp_max: int | None
    dp_set: bool
    blocks: tuple[int, ...]
    """Bloques de 3+ exigidos, de mayor a menor."""
    not_same_day: bool
    ideal_days: int
    """Días ideales de `distribution_uniform_week` (-1 sin rejilla)."""
    students: int
    lines: tuple[LineInfo, ...]
    needs_rooms: bool
    has_room_costs: bool
    """`True` si alguna línea puede sumar violaciones de aula."""
    ref_cells: frozenset[int]
    ref_rooms: dict[int, tuple[int, ...]]
    """Aulas de referencia por celda, una por línea (-1 sin aula)."""
    difficulty: float = 0.0
    cell_costs: dict[int, tuple[int, int, int]] = field(default_factory=dict)
    """Celda -> violaciones de deseos (profesor, clase, materia) de una sesión."""


@dataclass(slots=True)
class Model:
    """Proyecto compilado: todo lo estático que necesita la heurística."""

    project: UntisProject
    reference: Timetable | None
    weighting: Weighting
    weights: tuple[int, ...]
    grids: list[GridInfo]
    days: tuple[int, ...]
    day_index: dict[int, int]
    ndays: int
    resource_ids: list[str]
    resource_kind: list[EntityKind]
    entities: list[Entity]
    profiles: list[Profile]
    lessons: list[LessonInfo]
    lesson_by_number: dict[int, int]
    # Sesiones (índice = sid)
    s_lesson: list[int]
    s_index: list[int]
    s_duration: list[int]
    s_allowed: list[tuple[int, ...]]
    s_allowed_set: list[frozenset[int]]
    s_ref: list[int]
    s_fixed: list[bool]
    # Datos globales
    any_main: bool
    any_group: bool
    any_sequence: bool
    room_blocks: frozenset[tuple[int, int]]
    """`(aula, celda)` vetadas por un deseo -3 del aula."""
    room_requests: dict[int, tuple[TimeRequest, ...]]
    """Deseos blandos (-2, -1) por aula."""
    room_capacity: dict[int, int]
    """Capacidad de cada aula que la tiene definida."""
    mandatory: dict[tuple[int, int, int], int]
    """`(recurso, día, período)` de cada deseo +3 -> nº de deseos."""
    change_penalty: int = 0
    """Coste interno por sesión fuera de sus celdas de referencia (REPARAR)."""

    @property
    def nsessions(self) -> int:
        """Número total de sesiones (lectivas y obligaciones)."""
        return len(self.s_lesson)

    def scope_weights(self, names: tuple[str, ...]) -> tuple[int, ...]:
        """Pesos de los criterios de un ámbito, en su orden."""
        return tuple(self.weights[CRIT_INDEX[n]] for n in names)


def _chain(alternatives: dict[str, str | None], room: str) -> list[str]:
    """Cadena de aulas alternativas, idéntica a `evaluation._chain`."""
    cadena: list[str] = []
    actual = alternatives.get(room)
    while actual is not None and actual not in cadena and actual != room:
        cadena.append(actual)
        actual = alternatives.get(actual)
    return cadena


class _Resources:
    """Índice de recursos: profesores, clases y aulas en un único espacio."""

    def __init__(self) -> None:
        self.ids: list[str] = []
        self.kinds: list[EntityKind] = []
        self._index: dict[tuple[EntityKind, str], int] = {}

    def __call__(self, kind: EntityKind, rid: str) -> int:
        clave = (kind, rid)
        indice = self._index.get(clave)
        if indice is None:
            indice = len(self.ids)
            self._index[clave] = indice
            self.ids.append(rid)
            self.kinds.append(kind)
        return indice


def build_model(
    project: UntisProject,
    reference: Timetable | None,
    weighting: Weighting,
    *,
    change_penalty: int = 0,
) -> Model:
    """Compila el proyecto para la heurística."""
    ev = Evaluator(project)
    grids = _build_grids(project)
    grid_index = {g.grid.id: g.index for g in grids}
    dias = tuple(sorted({d for g in project.time_grids for d in g.days}))
    weights = tuple(weighting.weight(c) for c in CRITERIA)
    recurso = _Resources()

    for profe in project.teachers:
        recurso(EntityKind.TEACHER, profe.id)
    for clase in project.classes:
        recurso(EntityKind.CLASS, clase.id)
    for aula_obj in project.rooms:
        recurso(EntityKind.ROOM, aula_obj.id)

    # --- entidades evaluadas ------------------------------------------------ #
    unspec: defaultdict[tuple[EntityKind, str], list[tuple[UnspecifiedKind, int]]] = defaultdict(
        list
    )
    for u in project.unspecified_requests:
        unspec[(u.entity_kind, u.entity_id)].append((u.kind, u.count))
    profiles: list[Profile] = []
    profile_index: dict[Profile, int] = {}
    entities: list[Entity] = []
    entity_of: dict[tuple[EntityKind, str], int] = {}

    def perfil(p: Profile) -> int:
        if p not in profile_index:
            profile_index[p] = len(profiles)
            profiles.append(p)
        return profile_index[p]

    teachers = project.teacher_by_id
    for tid, g in sorted(ev.teacher_grid.items()):
        t_obj = teachers.get(tid)
        prof = Profile(
            is_class=False,
            grid=grid_index[g.id],
            ppd_min=t_obj.periods_per_day.min if t_obj is not None else None,
            ppd_max=t_obj.periods_per_day.max if t_obj is not None else None,
            ntp_day_min=t_obj.ntp_per_day.min if t_obj is not None else None,
            ntp_day_max=t_obj.ntp_per_day.max if t_obj is not None else None,
            consecutive_max=t_obj.consecutive_max if t_obj is not None else None,
            lunch_min=(t_obj.lunch_break.min or None) if t_obj is not None else None,
        )
        entity_of[(EntityKind.TEACHER, tid)] = len(entities)
        entities.append(
            Entity(
                index=len(entities),
                kind=EntityKind.TEACHER,
                id=tid,
                grid=grid_index[g.id],
                profile=perfil(prof),
                resource=recurso(EntityKind.TEACHER, tid),
                ntp_week=t_obj.ntp_per_week
                if t_obj is not None and t_obj.ntp_per_week.is_set
                else None,
                days_per_week_max=t_obj.days_per_week_max if t_obj is not None else None,
                unspecified=tuple(unspec.get((EntityKind.TEACHER, tid), ())),
            )
        )
    clases = project.class_by_id
    for cid, g in sorted(ev.class_grid.items()):
        c_obj = clases.get(cid)
        prof = Profile(
            is_class=True,
            grid=grid_index[g.id],
            ppd_min=c_obj.periods_per_day.min if c_obj is not None else None,
            ppd_max=c_obj.periods_per_day.max if c_obj is not None else None,
            lunch_min=(c_obj.lunch_break.min or None) if c_obj is not None else None,
        )
        entity_of[(EntityKind.CLASS, cid)] = len(entities)
        entities.append(
            Entity(
                index=len(entities),
                kind=EntityKind.CLASS,
                id=cid,
                grid=grid_index[g.id],
                profile=perfil(prof),
                resource=recurso(EntityKind.CLASS, cid),
                main_per_day=c_obj.main_subjects_per_day if c_obj is not None else None,
                unspecified=tuple(unspec.get((EntityKind.CLASS, cid), ())),
            )
        )

    # --- deseos ------------------------------------------------------------ #
    requests: defaultdict[tuple[EntityKind, str], list[TimeRequest]] = defaultdict(list)
    for req in project.time_requests:
        requests[(req.entity_kind, req.entity_id)].append(req)
    room_blocks: set[tuple[int, int]] = set()
    room_requests: dict[int, tuple[TimeRequest, ...]] = {}
    for (kind, eid), lista in requests.items():
        if kind is not EntityKind.ROOM:
            continue
        rid = recurso(EntityKind.ROOM, eid)
        blandos_aula = tuple(r for r in lista if -3 < r.value < 0)
        if blandos_aula:
            room_requests[rid] = blandos_aula
        for rejilla in project.time_grids:
            for d in rejilla.days:
                for periodo in rejilla.periods:
                    if any(x.is_block and x.covers(d, periodo.number) for x in lista):
                        room_blocks.add((rid, cell_code(d, periodo.number)))
    mandatory: Counter[tuple[int, int, int]] = Counter()
    for req in project.time_requests:
        if (
            req.is_mandatory
            and req.day is not None
            and req.period is not None
            and req.entity_kind in (EntityKind.TEACHER, EntityKind.CLASS, EntityKind.ROOM)
        ):
            mandatory[(recurso(req.entity_kind, req.entity_id), req.day, req.period)] += 1

    rooms_by_id = project.room_by_id
    alternativas = {x.id: x.alternative_room for x in project.rooms}
    students_of = {x.id: x.students for x in project.classes}
    subjects_by_id = project.subject_by_id
    subjects: dict[str, int] = {}
    grupos: dict[str, int] = {}

    def materia(nombre: str) -> int:
        return subjects.setdefault(nombre, len(subjects))

    # --- referencia ---------------------------------------------------------- #
    celdas_ref = reference_cells(reference)
    aulas_ref: defaultdict[tuple[int, int, int], dict[int, str]] = defaultdict(dict)
    uso_linea: defaultdict[tuple[int, int], Counter[str]] = defaultdict(Counter)
    uso_materia: defaultdict[str, Counter[str]] = defaultdict(Counter)
    lecciones_por_numero = project.lesson_by_number
    if reference is not None:
        for a in reference.assignments:
            if a.room is None:
                continue
            aulas_ref[(a.lesson_number, a.day, a.period)][a.line] = a.room
            uso_linea[(a.lesson_number, a.line)][a.room] += 1
            le_ref = lecciones_por_numero.get(a.lesson_number)
            if le_ref is not None and a.line < len(le_ref.lines):
                uso_materia[le_ref.lines[a.line].subject][a.room] += 1

    duraciones = all_session_durations(project, reference)
    celdas_por_rejilla = {g.id: cells_by_duration(g) for g in project.time_grids}

    lessons: list[LessonInfo] = []
    s_lesson: list[int] = []
    s_index: list[int] = []
    s_duration: list[int] = []
    s_allowed: list[tuple[int, ...]] = []
    s_ref: list[int] = []
    s_fixed: list[bool] = []

    w_room_opt = weights[CRIT_INDEX["room_optimization"]]
    w_chain = weights[CRIT_INDEX["room_alternative_chain"]]
    w_req = weights[CRIT_INDEX["subject_required_room"]]
    w_cap = weights[CRIT_INDEX["room_capacity"]]

    for le in project.active_lessons:
        if le.periods_per_week <= 0 or le.number not in duraciones:
            continue
        li = len(lessons)
        duty = is_duty(le)
        gi = grid_index.get(le.time_grid, -1)
        subj = le.subjects[0] if le.subjects else ""
        s_obj = subjects_by_id.get(subj)
        grupo = -1
        if s_obj is not None and s_obj.subject_group is not None:
            grupo = grupos.setdefault(s_obj.subject_group, len(grupos))
        res: list[int] = []
        ents: list[int] = []
        if not duty:
            for tid in le.teachers:
                res.append(recurso(EntityKind.TEACHER, tid))
                if (EntityKind.TEACHER, tid) in entity_of:
                    ents.append(entity_of[(EntityKind.TEACHER, tid)])
            for cid in le.classes:
                res.append(recurso(EntityKind.CLASS, cid))
                if (EntityKind.CLASS, cid) in entity_of:
                    ents.append(entity_of[(EntityKind.CLASS, cid)])
        nsd = le.not_same_day or any(
            subjects_by_id[line.subject].not_same_day
            for line in le.lines
            if line.subject in subjects_by_id
        )
        ideal = -1
        if gi >= 0:
            ideal = min(le.periods_per_week - (le.double_periods.min or 0), len(grids[gi].days))
        alumnos = sum(students_of.get(x, 0) for x in le.classes)

        # Aulas: candidatas por línea, ordenadas por su coste estático.
        lineas: list[LineInfo] = []
        costes_aula = False
        for i, line in enumerate(le.lines):
            materia_obj = subjects_by_id.get(line.subject)
            exigida = materia_obj.required_room if materia_obj is not None else None
            cadena = _chain(alternativas, line.room) if line.room is not None else []
            usadas = uso_linea.get((le.number, i), Counter())
            orden: list[str] = []
            for nombre in (
                *([line.room] if line.room is not None else []),
                *cadena,
                *([exigida] if exigida is not None else []),
                *([line.alternative_room] if line.alternative_room is not None else []),
                *(r for r, _ in usadas.most_common()),
                *(r for r, _ in uso_materia.get(line.subject, Counter()).most_common()),
            ):
                if nombre not in orden:
                    orden.append(nombre)
            necesita = not duty and (line.room is not None or bool(usadas) or exigida is not None)
            costes_aula = costes_aula or line.room is not None or exigida is not None

            def coste(
                r: str,
                cadena: list[str] = cadena,
                pedida: str | None = line.room,
                exigida: str | None = exigida,
                alumnos: int = alumnos,
            ) -> int:
                c = 0
                if pedida is not None and r != pedida and r not in cadena:
                    c += w_room_opt
                if r in cadena:
                    c += w_chain * (cadena.index(r) + 1)
                if exigida is not None and r != exigida:
                    c += w_req
                aula = rooms_by_id.get(r)
                if alumnos and aula is not None and aula.capacity is not None:
                    c += w_cap if alumnos > aula.capacity else 0
                return c

            orden = sorted(orden, key=coste)[:MAX_ROOM_CANDIDATES] if necesita else []
            lineas.append(
                LineInfo(
                    needs_room=necesita,
                    candidates=tuple(recurso(EntityKind.ROOM, r) for r in orden),
                    room=recurso(EntityKind.ROOM, line.room) if line.room is not None else -1,
                    chain=tuple(recurso(EntityKind.ROOM, r) for r in cadena),
                    required=recurso(EntityKind.ROOM, exigida) if exigida is not None else -1,
                )
            )

        ref = celdas_ref.get(le.number, [])
        ref_rooms: dict[int, tuple[int, ...]] = {}
        for d, p in ref:
            por_linea = aulas_ref.get((le.number, d, p), {})
            ref_rooms[cell_code(d, p)] = tuple(
                recurso(EntityKind.ROOM, por_linea[i]) if i in por_linea else -1
                for i in range(len(le.lines))
            )
            costes_aula = costes_aula or bool(por_linea)

        # Deseos de profesor, clase y materia: -3 veta la celda, -2/-1 cuestan.
        vetos: list[TimeRequest] = []
        blandos: list[tuple[int, TimeRequest]] = []
        for k, (kind, ids) in enumerate(
            (
                (EntityKind.TEACHER, le.teachers),
                (EntityKind.CLASS, le.classes),
                (EntityKind.SUBJECT, (subj,)),
            )
        ):
            for eid in ids:
                for req in requests.get((kind, eid), ()):
                    if req.is_block:
                        vetos.append(req)
                    elif -3 < req.value < 0:
                        blandos.append((k, req))

        info = LessonInfo(
            index=li,
            number=le.number,
            lesson=le,
            grid=gi,
            duty=duty,
            fixed=le.fixed,
            ppw=le.periods_per_week,
            sids=(),
            resources=tuple(res),
            entities=tuple(ents),
            subject=materia(subj),
            main=bool(s_obj is not None and s_obj.main_subject),
            group=grupo,
            sequence_after=materia(le.sequence_after) if le.sequence_after is not None else -1,
            no_teacher=sum(1 for line in le.lines if line.teacher is None),
            dp_min=le.double_periods.min,
            dp_max=le.double_periods.max,
            dp_set=le.double_periods.is_set,
            blocks=tuple(sorted((b for b in le.block if b >= 3), reverse=True)),
            not_same_day=nsd,
            ideal_days=ideal,
            students=alumnos,
            lines=tuple(lineas),
            needs_rooms=any(x.needs_room for x in lineas),
            has_room_costs=costes_aula,
            ref_cells=frozenset(cell_code(d, p) for d, p in ref),
            ref_rooms=ref_rooms,
        )

        sids: list[int] = []
        por_duracion = celdas_por_rejilla.get(le.time_grid, {})
        for i, dur in enumerate(duraciones[le.number]):
            sids.append(len(s_lesson))
            celda_ref = cell_code(*ref[i]) if i < len(ref) else -1
            permitidas = tuple(
                cell_code(d, p)
                for d, p in por_duracion.get(dur, ())
                if not any(r.covers(d, p) for r in vetos)
            )
            fija = le.fixed and celda_ref >= 0
            if fija:
                permitidas = (celda_ref,)
            elif duty and not permitidas and celda_ref >= 0:
                # Obligación en un recreo (vigilancia): solo su celda de referencia.
                permitidas = (celda_ref,)
            s_lesson.append(li)
            s_index.append(i)
            s_duration.append(dur)
            s_allowed.append(permitidas)
            s_ref.append(celda_ref)
            s_fixed.append(fija)
        info.sids = tuple(sids)
        if blandos:
            for celda in {x for s in sids for x in s_allowed[s]}:
                por_tipo = [0, 0, 0]
                for k, req in blandos:
                    if req.covers(cell_day(celda), cell_period(celda)):
                        por_tipo[k] += -req.value
                info.cell_costs[celda] = (por_tipo[0], por_tipo[1], por_tipo[2])
        lessons.append(info)

    room_capacity = {
        recurso(EntityKind.ROOM, r.id): r.capacity for r in project.rooms if r.capacity is not None
    }
    return Model(
        project=project,
        reference=reference,
        weighting=weighting,
        weights=weights,
        grids=grids,
        days=dias,
        day_index={d: i for i, d in enumerate(dias)},
        ndays=len(dias),
        resource_ids=recurso.ids,
        resource_kind=recurso.kinds,
        entities=entities,
        profiles=profiles,
        lessons=lessons,
        lesson_by_number={info.number: info.index for info in lessons},
        s_lesson=s_lesson,
        s_index=s_index,
        s_duration=s_duration,
        s_allowed=s_allowed,
        s_allowed_set=[frozenset(a) for a in s_allowed],
        s_ref=s_ref,
        s_fixed=s_fixed,
        any_main=any(info.main for info in lessons),
        any_group=any(info.group >= 0 for info in lessons),
        any_sequence=any(info.sequence_after >= 0 for info in lessons),
        room_blocks=frozenset(room_blocks),
        room_requests=room_requests,
        room_capacity=room_capacity,
        mandatory=dict(mandatory),
        change_penalty=change_penalty,
    )
