"""Modelos de vista planos para la GUI (Fase 5): sin Qt, sin lógica de negocio.

La app de escritorio nunca toca el modelo del solver ni el problema canónico
directamente: consume estas *dataclasses* inmutables, que el motor reconstruye
desde el ``.bjs`` (problema canónico + solución). Aquí vive la lógica de
presentación de datos (clasificar recursos por *tag*, ubicar cada clase en su
día/período, contar KPIs); la UI solo pinta.

Nada de esto importa Qt: se puede probar de cabeza, y garantiza que las reglas
del negocio no se filtren a la interfaz.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace

from ..core.problem import SchedulingProblem
from ..core.solution import Solution

# Esquema de tags que el adaptador académico graba en los recursos canónicos.
# Se replican aquí (constantes locales) para no acoplar la capa de presentación
# al paquete ``academic``: el ``.bjs`` es canónico y basta con estos prefijos.
_TEACHER = "teacher"
_GROUP = "group"
_ROOM = "room"
_TEACHER_PREFIX = "teacher#"
_GROUP_PREFIX = "group#"
_ROOMTYPE_PREFIX = "roomtype#"
_SUBJECT_SEP = " · "


# --------------------------------------------------------------------------- #
# Tablas de entidades (Data Manager)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class EntityRow:
    """Una fila de una tabla de entidades. ``key`` identifica la entidad."""

    key: str
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntityTable:
    """Una tabla tipo Excel de una clase de entidad (docentes, aulas...).

    ``fields`` nombra semánticamente cada columna (``abbrev``, ``full_name``,
    ``email``, ``section``, ``seats``, ``size``, ``color``...) para que la UI
    sepa cómo enrutar cada edición sin conocer el orden de columnas.
    """

    kind: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[EntityRow, ...]
    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityTables:
    """El conjunto de tablas que alimenta el Data Manager."""

    teachers: EntityTable
    rooms: EntityTable
    groups: EntityTable
    subjects: EntityTable

    def as_tuple(self) -> tuple[EntityTable, ...]:
        return (self.teachers, self.rooms, self.groups, self.subjects)


def _kind_of(tags: frozenset[str]) -> str | None:
    if _TEACHER in tags:
        return _TEACHER
    if _GROUP in tags:
        return _GROUP
    if _ROOM in tags:
        return _ROOM
    return None


def _unique_tag(tags: frozenset[str], prefix: str) -> str | None:
    return next((t for t in tags if t.startswith(prefix)), None)


def _room_type(tags: frozenset[str]) -> str:
    tag = _unique_tag(tags, _ROOMTYPE_PREFIX)
    return tag[len(_ROOMTYPE_PREFIX) :] if tag is not None else "—"


def _subject_of(task_name: str) -> str:
    return task_name.split(_SUBJECT_SEP, 1)[0]


def entity_tables(
    problem: SchedulingProblem,
    registered_subjects: tuple[str, ...] = (),
    resource_info: dict[int, dict[str, str]] | None = None,
    subject_info: dict[str, dict[str, str]] | None = None,
) -> EntityTables:
    """Reconstruye las tablas de docentes/aulas/grupos/materias, estilo Untis.

    El nombre canónico del recurso actúa como **abreviatura** (lo que se ve en el
    horario); ``resource_info``/``subject_info`` aportan los datos maestros
    (nombre completo, e-mail, sección, aula propia/alternativa, color de materia).
    ``registered_subjects`` son las materias dadas de alta explícitamente.
    """
    res_info = resource_info or {}
    sub_info = subject_info or {}
    # Demanda por tag único: cuántas tareas requiere cada docente/grupo, y si su
    # dominio temporal está restringido (disponibilidad parcial).
    tasks_per_tag: dict[str, int] = defaultdict(int)
    restricted_tags: set[str] = set()
    size_of_group: dict[str, int] = {}
    subjects: dict[str, tuple[int, set[str]]] = {}
    for task in problem.tasks:
        subject = _subject_of(task.name)
        count, teachers = subjects.get(subject, (0, set()))
        for req in task.requirements:
            tasks_per_tag[req.tag] += 1
            if req.tag.startswith(_TEACHER_PREFIX):
                if task.allowed_starts is not None:
                    restricted_tags.add(req.tag)
                teachers.add(req.tag)
            elif req.tag.startswith(_GROUP_PREFIX):
                size_of_group[req.tag] = task.attribute("size", size_of_group.get(req.tag, 0))
        subjects[subject] = (count + 1, teachers)

    teachers_rows: list[EntityRow] = []
    rooms_rows: list[EntityRow] = []
    groups_rows: list[EntityRow] = []
    for res in sorted(problem.resources, key=lambda r: int(r.id)):
        kind = _kind_of(res.tags)
        rid = str(int(res.id))
        info = res_info.get(int(res.id), {})
        if kind == _TEACHER:
            tag = _unique_tag(res.tags, _TEACHER_PREFIX) or ""
            avail = "Parcial" if tag in restricted_tags else "Completa"
            teachers_rows.append(
                EntityRow(
                    rid,
                    (
                        res.name,
                        info.get("full_name", ""),
                        info.get("email", ""),
                        info.get("section", ""),
                        str(tasks_per_tag.get(tag, 0)),
                        avail,
                    ),
                )
            )
        elif kind == _ROOM:
            rooms_rows.append(
                EntityRow(
                    rid,
                    (
                        res.name,
                        info.get("full_name", ""),
                        str(res.attribute("seats")),
                        info.get("alt_room", ""),
                    ),
                )
            )
        elif kind == _GROUP:
            tag = _unique_tag(res.tags, _GROUP_PREFIX) or ""
            size = res.attribute("size") or size_of_group.get(tag, 0)
            groups_rows.append(
                EntityRow(
                    rid,
                    (
                        res.name,
                        info.get("full_name", ""),
                        info.get("section", ""),
                        info.get("home_room", ""),
                        str(size),
                        str(tasks_per_tag.get(tag, 0)),
                    ),
                )
            )

    for name in registered_subjects:
        subjects.setdefault(name, (0, set()))  # materias sin clases aún
    subjects_rows = tuple(
        EntityRow(
            name,
            (
                name,
                sub_info.get(name, {}).get("full_name", ""),
                sub_info.get(name, {}).get("section", ""),
                sub_info.get(name, {}).get("color", ""),
                str(count),
                str(len(teachers)),
            ),
        )
        for name, (count, teachers) in sorted(subjects.items())
    )

    return EntityTables(
        teachers=EntityTable(
            _TEACHER,
            "Docentes",
            ("Abrev.", "Nombre completo", "E-mail", "Sección", "Clases", "Disponibilidad"),
            tuple(teachers_rows),
            ("abbrev", "full_name", "email", "section", "classes", "availability"),
        ),
        rooms=EntityTable(
            _ROOM,
            "Aulas",
            ("Abrev.", "Nombre completo", "Capacidad", "Aula alternativa"),
            tuple(rooms_rows),
            ("abbrev", "full_name", "seats", "alt_room"),
        ),
        groups=EntityTable(
            _GROUP,
            "Grupos",
            ("Abrev.", "Nombre completo", "Sección", "Aula propia", "Tamaño", "Clases"),
            tuple(groups_rows),
            ("abbrev", "full_name", "section", "home_room", "size", "classes"),
        ),
        subjects=EntityTable(
            "subject",
            "Materias",
            ("Abreviatura", "Nombre completo", "Sección", "Color", "Sesiones", "Docentes"),
            subjects_rows,
            ("abbrev", "full_name", "section", "color", "sessions", "teachers"),
        ),
    )


# --------------------------------------------------------------------------- #
# Lecciones (carga horaria, la vista "N.lec" de Untis)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class LessonRow:
    """Una lección: una asignación (materia + docentes + grupos + aulas) con sus
    horas semanales (``hours`` = número de sesiones). Equivale al N.lec de Untis;
    puede acoplar varios docentes/grupos/aulas (Kopplung)."""

    key: str  # identificador estable (ids de las clases)
    task_ids: tuple[int, ...]
    subject: str
    teacher_ids: tuple[int, ...]
    teachers: tuple[str, ...]  # abreviaturas
    group_ids: tuple[int, ...]
    groups: tuple[str, ...]
    room_ids: tuple[int, ...]  # aulas fijas (vacío = el solver elige del pool)
    rooms: tuple[str, ...]
    hours: int
    duration: int
    coupling_id: int = -1  # id del acople (lecciones simultáneas); -1 = sin acoplar


def lesson_rows(problem: SchedulingProblem) -> tuple[LessonRow, ...]:
    """Agrupa las clases en lecciones: misma materia + mismos requerimientos.

    Cada grupo de clases idénticas (materia, docentes, grupos, aulas, duración)
    es una lección con ``hours`` sesiones semanales, como la vista de lecciones
    de Untis por grupo o por docente.
    """
    tag_owner: dict[str, tuple[int, str]] = {}
    for res in problem.resources:
        for tag in res.tags:
            if tag.startswith((_TEACHER_PREFIX, _GROUP_PREFIX, "room#")):
                tag_owner[tag] = (int(res.id), res.name)

    grouped: dict[tuple[str, tuple[str, ...], int, int], list[int]] = defaultdict(list)
    for task in problem.tasks:
        subject = _subject_of(task.name)
        signature = (
            subject,
            tuple(sorted(r.tag for r in task.requirements)),
            task.duration,
            task.attribute("coupling", -1),
        )
        grouped[signature].append(int(task.id))

    rows: list[LessonRow] = []
    for (subject, tags, duration, coupling_id), task_ids in grouped.items():
        teacher_ids: list[int] = []
        teachers: list[str] = []
        group_ids: list[int] = []
        groups: list[str] = []
        room_ids: list[int] = []
        rooms: list[str] = []
        for tag in tags:
            owner = tag_owner.get(tag)
            if owner is None:
                continue  # tags genéricos (room, roomtype#...) = pool de aulas
            if tag.startswith(_TEACHER_PREFIX):
                teacher_ids.append(owner[0])
                teachers.append(owner[1])
            elif tag.startswith(_GROUP_PREFIX):
                group_ids.append(owner[0])
                groups.append(owner[1])
            elif tag.startswith("room#"):
                room_ids.append(owner[0])
                rooms.append(owner[1])
        ordered = tuple(sorted(task_ids))
        rows.append(
            LessonRow(
                key="-".join(str(t) for t in ordered),
                task_ids=ordered,
                subject=subject,
                teacher_ids=tuple(teacher_ids),
                teachers=tuple(teachers),
                group_ids=tuple(group_ids),
                groups=tuple(groups),
                room_ids=tuple(room_ids),
                rooms=tuple(rooms),
                hours=len(ordered),
                duration=duration,
                coupling_id=coupling_id,
            )
        )
    rows.sort(key=lambda r: (r.groups, r.subject))
    return tuple(rows)


# --------------------------------------------------------------------------- #
# Selector de foco de la rejilla (por docente / grupo / aula)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class FocusOption:
    """Un recurso por el que se puede filtrar la rejilla de horario."""

    resource_id: int
    kind: str
    name: str


def focus_options(problem: SchedulingProblem) -> tuple[FocusOption, ...]:
    """Docentes, grupos y aulas disponibles como foco del Schedule Editor."""
    options: list[FocusOption] = []
    for res in problem.resources:
        kind = _kind_of(res.tags)
        if kind is not None:
            options.append(FocusOption(int(res.id), kind, res.name))
    order = {_TEACHER: 0, _GROUP: 1, _ROOM: 2}
    options.sort(key=lambda o: (order.get(o.kind, 9), o.name))
    return tuple(options)


# --------------------------------------------------------------------------- #
# Rejilla de horario (Schedule Editor)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class TimetableCell:
    """Una clase ubicada en (día, período) para el recurso en foco.

    Incluye los ids de docente/grupo/aula para las **vistas enlazadas**: al hacer
    clic en la clase se puede saltar al horario de su docente o de su aula.
    """

    day: int
    period: int
    duration: int
    task_id: int
    subject: str
    teacher: str
    group: str
    room: str
    conflict: bool
    teacher_id: int = -1
    group_id: int = -1
    room_id: int = -1


@dataclass(frozen=True, slots=True)
class MoveTarget:
    """Una celda (día, período) como destino posible de una clase al arrastrarla.

    ``feasible`` indica si la clase cabe ahí respetando las reglas duras
    (docente/grupo libres, aula disponible, cabe en el día); ``reason`` explica el
    motivo cuando no.
    """

    day: int
    period: int
    feasible: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TimetableView:
    """Rejilla semanal dia x periodo reconstruida para un recurso en foco."""

    focus_id: int
    focus_kind: str
    focus_name: str
    days: int
    periods_per_day: int
    cells: tuple[TimetableCell, ...]


def _name_by_tag(problem: SchedulingProblem, prefix: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for res in problem.resources:
        tag = _unique_tag(res.tags, prefix)
        if tag is not None:
            out[tag] = res.name
    return out


def timetable_view(
    problem: SchedulingProblem, solution: Solution | None, focus_id: int
) -> TimetableView:
    """Ubica cada clase del recurso ``focus_id`` en su celda (día, período).

    Filtra por pertenencia al recurso en foco (``focus_id in resource_ids``), lo
    que sirve por igual para docente, grupo o aula. Marca en conflicto las clases
    del foco que se solapan en el tiempo (nunca deberían, salvo horario roto).
    """
    focus = next(r for r in problem.resources if int(r.id) == focus_id)
    focus_kind = _kind_of(focus.tags) or "resource"

    segments = problem.grid.segments
    day_of = {seg.id: i for i, seg in enumerate(segments)}
    periods_per_day = max(seg.length for seg in segments)

    teacher_names = _name_by_tag(problem, _TEACHER_PREFIX)
    group_names = _name_by_tag(problem, _GROUP_PREFIX)
    id_by_tag = {
        tag: int(r.id)
        for r in problem.resources
        for tag in r.tags
        if tag.startswith((_TEACHER_PREFIX, _GROUP_PREFIX))
    }
    room_name_by_id = {int(r.id): r.name for r in problem.resources if _ROOM in r.tags}

    cells: list[TimetableCell] = []
    occupancy: dict[int, list[int]] = defaultdict(list)  # slot -> índices de celda
    if solution is not None:
        for assignment in solution.assignments:
            if focus_id not in {int(r) for r in assignment.resource_ids}:
                continue
            task = problem.task_by_id(assignment.task_id)
            seg = problem.grid.segment_of(assignment.start)
            day = day_of[seg.id]
            period = int(assignment.start) - int(seg.start)
            teacher_tag = next((r.tag for r in task.requirements if r.tag in teacher_names), None)
            group_tag = next((r.tag for r in task.requirements if r.tag in group_names), None)
            room_id = next(
                (int(r) for r in assignment.resource_ids if int(r) in room_name_by_id), -1
            )
            index = len(cells)
            cells.append(
                TimetableCell(
                    day=day,
                    period=period,
                    duration=task.duration,
                    task_id=int(task.id),
                    subject=_subject_of(task.name),
                    teacher=teacher_names.get(teacher_tag, "—") if teacher_tag else "—",
                    group=group_names.get(group_tag, "—") if group_tag else "—",
                    room=room_name_by_id.get(room_id, "—"),
                    conflict=False,
                    teacher_id=id_by_tag.get(teacher_tag, -1) if teacher_tag else -1,
                    group_id=id_by_tag.get(group_tag, -1) if group_tag else -1,
                    room_id=room_id,
                )
            )
            for offset in range(task.duration):
                occupancy[int(assignment.start) + offset].append(index)

    clashing = {i for users in occupancy.values() if len(users) > 1 for i in users}
    if clashing:
        cells = [
            cell if i not in clashing else _with_conflict(cell) for i, cell in enumerate(cells)
        ]

    return TimetableView(
        focus_id=focus_id,
        focus_kind=focus_kind,
        focus_name=focus.name,
        days=len(segments),
        periods_per_day=periods_per_day,
        cells=tuple(cells),
    )


def _with_conflict(cell: TimetableCell) -> TimetableCell:
    return replace(cell, conflict=True)


# --------------------------------------------------------------------------- #
# Tablero (Dashboard)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class DashboardStats:
    """KPIs de portada del proyecto."""

    project_name: str
    teachers: int
    rooms: int
    groups: int
    subjects: int
    tasks: int
    solved: bool
    quality_score: float | None = None
    hard_violations: int | None = None
    room_utilization_pct: float | None = None
    teacher_gaps: int | None = None
    last_optimized: str | None = None


# --------------------------------------------------------------------------- #
# Validación (Validation Center)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ValidationItem:
    """Un hallazgo de validación con pista de navegación."""

    severity: str  # "error" | "warning"
    message: str
    where: str = ""


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Resultado consolidado de validar un proyecto."""

    feasible: bool
    items: tuple[ValidationItem, ...] = ()

    @property
    def errors(self) -> tuple[ValidationItem, ...]:
        return tuple(i for i in self.items if i.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationItem, ...]:
        return tuple(i for i in self.items if i.severity == "warning")


# --------------------------------------------------------------------------- #
# Catálogo de restricciones (Constraint Manager)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ConstraintRow:
    """Una restricción del catálogo con su estado configurado (activa/tier/peso).

    En el Constraint Manager no se *programan* restricciones: se **editan**. Las
    blandas (``kind == "soft"``) permiten ajustar tier y ponderación pedagógica;
    las duras solo activarse/desactivarse (peso infinito).
    """

    rule_id: str  # == plugin_name (clave de PluginSetting)
    catalog_id: str  # p. ej. "SC-02"
    name: str
    description: str
    kind: str  # "hard" | "soft"
    enabled: bool
    weight: int
    tier: int
    default_weight: int
    default_tier: int
    editable_weight: bool
    editable_tier: bool


# --------------------------------------------------------------------------- #
# Informes (Reports)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ReportTable:
    """Un informe tabular listo para mostrar o exportar (CSV/HTML)."""

    key: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


# --------------------------------------------------------------------------- #
# Resultado de una optimización (Optimization Console)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SolveOutcome:
    """Desenlace estructurado de solve/optimize (nunca lanza a la GUI)."""

    solved: bool
    status: str  # "solved" | "infeasible" | "timeout" | "error"
    solver: str
    message: str
    metrics: dict[str, object] | None = None
