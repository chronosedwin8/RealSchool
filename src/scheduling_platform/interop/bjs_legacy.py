"""Convertidor de un solo uso `.bjs` (heredado) -> `UntisProject`.

**Puente heredado**: es el ÚNICO módulo de `interop` autorizado a leer las
estructuras antiguas. Importa `scheduling_platform.application` (que a su vez
depende de `core` y `serialization`) para abrir el `.bjs` con el lector
existente (`open_project`), y traduce el problema canónico a vocabulario Untis.
No escribe `.bjs` ni se usa en el flujo normal: cada curso real se convierte una
vez a `.rsp` y a partir de ahí manda el `.rsp` (`REFACTOR_UNTIS_MAESTRO.md`,
sección 10). Por eso tampoco importa `core` directamente: todo lo canónico llega
tipado a través de `BjsProject`.

Mapeo (el mejor posible; el `.bjs` no guarda todo lo que modela Untis):

- Recursos con tag `teacher#…` -> `Teacher`; `group#…` -> `SchoolClass`;
  `room#…` o `room` -> `Room`. El nombre canónico (la abreviatura) es el id; si
  dos recursos del mismo tipo comparten nombre, el segundo recibe `#<id>`.
  `resource_info` aporta nombre completo, e-mail, sección (-> `Department`),
  aula propia y aula alternativa; los atributos `size`/`seats`, alumnos y
  capacidad.
- Materias: prefijo del nombre de tarea antes de ` · `, más las registradas en
  `subjects`; `subject_info["full_name"]` es el nombre.
- Lecciones: las tareas se agrupan como la vista de lecciones de la app
  (`lesson_rows`: misma materia, requerimientos, bloque, acople y semana). Cada
  grupo es una línea (una por docente si hay docencia compartida); los grupos que
  comparten el atributo `coupling` forman una sola `Lesson` multilínea.
  `periods_per_week` es la suma de duraciones de sus sesiones (= nº de sesiones
  cuando son simples); las sesiones de duración > 1 llenan `block`.
- `SchoolWeek` -> `TimeGrid` (recreos -> `PeriodKind.BREAK`, corte Mañana/Tarde ->
  `HalfDay`, horas de reloj `HH:MM`). Si una semana no trae horas se sintetizan
  (08:00 + 50 min por período) para cumplir las invariantes de `PeriodDef`. Si
  hay tareas sin semana asignada (o no hay semanas), se añade la rejilla
  `"default"` derivada de la rejilla canónica.
- `availability` -> `TimeRequest` con valor -3 por celda bloqueada.
- Ventana de almuerzo -> `lunch_break = MinMax(min=1)` en todos los docentes.
- `options.avoid_same_subject_same_day=False` -> deslizador
  `distribution_same_day = 0`.
- Solución -> un `Timetable` con id `"bjs"` (una `Assignment` por período
  ocupado y línea) y penalizaciones como `CriterionScore` de peso 1.

No se recupera: bloqueos por hora de reloj de docentes (`time_blocks`), la
configuración de plugins y del solver, métricas e historial, colores de materia,
`allow_break_split_block`, ni el acople simultáneo de más de 10 líneas (se parte
en lecciones de 10 líneas como máximo, el límite de Untis).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ..application.project import BjsProject, SchoolWeek, open_project
from ..application.view_models import LessonRow, lesson_rows
from ..untis_model import (
    LINES_PER_LESSON,
    REQUEST_MIN,
    Assignment,
    CriterionScore,
    Department,
    EntityKind,
    Evaluation,
    HalfDay,
    Lesson,
    LessonLine,
    MinMax,
    PeriodDef,
    PeriodKind,
    Room,
    SchoolClass,
    SchoolInfo,
    Subject,
    Teacher,
    TimeGrid,
    TimeRequest,
    Timetable,
    UntisProject,
    Weighting,
    double_periods_from_block,
)

__all__ = ["DEFAULT_GRID_ID", "TIMETABLE_ID", "convert_bjs_project", "load_bjs_as_project"]

#: Id de la rejilla derivada de la rejilla canónica (tareas sin semana lectiva).
DEFAULT_GRID_ID: Final = "default"
#: Id del horario que se reconstruye a partir de la solución del `.bjs`.
TIMETABLE_ID: Final = "bjs"
_SUBJECT_SEP: Final = " · "
_SYNTH_START: Final = 8 * 60
_SYNTH_STEP: Final = 50
_SYNTH_LENGTH: Final = 45
_LAST_MINUTE: Final = 24 * 60 - 1


def load_bjs_as_project(path: str | Path) -> UntisProject:
    """Abre un `.bjs` heredado y lo convierte en `UntisProject` (solo lectura)."""
    return convert_bjs_project(open_project(path))


# --------------------------------------------------------------------------- #
# Recursos
# --------------------------------------------------------------------------- #


def _kind_of(tags: frozenset[str]) -> EntityKind | None:
    if any(t.startswith("teacher#") for t in tags) or "teacher" in tags:
        return EntityKind.TEACHER
    if any(t.startswith("group#") for t in tags) or "group" in tags:
        return EntityKind.CLASS
    if any(t.startswith("room#") for t in tags) or "room" in tags:
        return EntityKind.ROOM
    return None


@dataclass(slots=True)
class _Ids:
    """Ids Untis asignados a cada recurso canónico, por tipo."""

    kind: dict[int, EntityKind] = field(default_factory=dict)
    ids: dict[int, str] = field(default_factory=dict)
    by_name: dict[tuple[EntityKind, str], str] = field(default_factory=dict)

    def room_ref(self, raw: str) -> str | None:
        """Resuelve una referencia textual a aula (abreviatura) a su id Untis."""
        texto = raw.strip()
        if not texto:
            return None
        return self.by_name.get((EntityKind.ROOM, texto), texto)


def _assign_ids(bjs: BjsProject) -> _Ids:
    out = _Ids()
    usados: set[tuple[EntityKind, str]] = set()
    for res in sorted(bjs.problem.resources, key=lambda r: int(r.id)):
        kind = _kind_of(res.tags)
        if kind is None:
            continue
        rid = int(res.id)
        nombre = res.name.strip()
        ident = nombre if (kind, nombre) not in usados else f"{nombre}#{rid}"
        usados.add((kind, ident))
        out.kind[rid] = kind
        out.ids[rid] = ident
        out.by_name.setdefault((kind, nombre), ident)
    return out


# --------------------------------------------------------------------------- #
# Rejillas (SchoolWeek -> TimeGrid)
# --------------------------------------------------------------------------- #


def _clock(texto: str) -> int | None:
    partes = texto.strip().split(":")
    if len(partes) != 2 or not all(p.isdigit() for p in partes):
        return None
    horas, mins = int(partes[0]), int(partes[1])
    if not (0 <= horas <= 23 and 0 <= mins <= 59):
        return None
    return horas * 60 + mins


def _period(index: int, week: SchoolWeek | None) -> PeriodDef:
    """Período `index` (0-based) de una semana lectiva, con horas reales o sintéticas."""
    inicio = _SYNTH_START + index * _SYNTH_STEP
    fin = inicio + _SYNTH_LENGTH
    kind, half = PeriodKind.LESSON, HalfDay.MORNING
    if week is not None:
        if index < len(week.periods):
            a, b = _clock(week.periods[index].start), _clock(week.periods[index].end)
            if a is not None and b is not None and b > a:
                inicio, fin = a, b
        if index in week.breaks:
            kind = PeriodKind.BREAK
        if 0 <= week.afternoon_from <= index:
            half = HalfDay.AFTERNOON
    if inicio >= _LAST_MINUTE:  # rejilla sintética desbordando el día: se comprime al final
        inicio, fin = _LAST_MINUTE - 1, _LAST_MINUTE
    return PeriodDef(number=index + 1, start=inicio, end=fin, kind=kind, half_day=half)


def _grid_ids(weeks: tuple[SchoolWeek, ...]) -> list[str]:
    ids: list[str] = []
    for i, w in enumerate(weeks):
        base = w.name.strip() or f"SW{i + 1}"
        ident = base if base not in ids and base != DEFAULT_GRID_ID else f"{base}#{i + 1}"
        ids.append(ident)
    return ids


def _time_grids(bjs: BjsProject, grid_ids: list[str], need_default: bool) -> tuple[TimeGrid, ...]:
    segmentos = bjs.problem.grid.segments
    n_dias = len(segmentos)
    n_periodos = max(s.length for s in segmentos)
    grids: list[TimeGrid] = []
    for ident, week in zip(grid_ids, bjs.school_weeks, strict=True):
        tope = min(week.max_periods, n_periodos) if week.max_periods > 0 else n_periodos
        dias = min(week.days, n_dias) if week.days > 0 else n_dias
        grids.append(
            TimeGrid(
                id=ident,
                name=week.name,
                days=tuple(range(1, max(dias, 1) + 1)),
                periods=tuple(_period(i, week) for i in range(tope)),
            )
        )
    if need_default:
        grids.append(
            TimeGrid(
                id=DEFAULT_GRID_ID,
                name="Rejilla del .bjs",
                days=tuple(range(1, n_dias + 1)),
                periods=tuple(_period(i, None) for i in range(n_periodos)),
            )
        )
    return tuple(grids)


# --------------------------------------------------------------------------- #
# Lecciones
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _LineGroup:
    """Una fila de `lesson_rows` traducida a líneas Untis."""

    row: LessonRow
    lines: tuple[LessonLine, ...]


def _row_lines(row: LessonRow, ids: _Ids) -> tuple[LessonLine, ...]:
    clases = tuple(dict.fromkeys(ids.ids[g] for g in row.group_ids if g in ids.ids))
    docentes: list[str | None] = [ids.ids[t] for t in row.teacher_ids if t in ids.ids]
    aulas = [ids.ids[r] for r in row.room_ids if r in ids.ids]
    if not docentes:
        docentes = [None]
    return tuple(
        LessonLine(
            subject=row.subject,
            teacher=docente,
            classes=clases,
            room=aulas[i] if i < len(aulas) else (aulas[0] if aulas else None),
        )
        for i, docente in enumerate(docentes)
    )


def _lesson_groups(rows: tuple[LessonRow, ...], ids: _Ids) -> list[list[_LineGroup]]:
    """Agrupa las filas en lecciones: una por fila, o una por acople."""
    ordenadas = sorted(rows, key=lambda r: min(r.task_ids))
    lecciones: list[list[_LineGroup]] = []
    por_acople: dict[int, list[_LineGroup]] = {}
    for row in ordenadas:
        grupo = _LineGroup(row, _row_lines(row, ids))
        if row.coupling_id >= 0:
            if row.coupling_id in por_acople:
                por_acople[row.coupling_id].append(grupo)
                continue
            por_acople[row.coupling_id] = [grupo]
            lecciones.append(por_acople[row.coupling_id])
        else:
            lecciones.append([grupo])
    # Untis admite como mucho 10 líneas por lección: se trocea en orden.
    troceadas: list[list[_LineGroup]] = []
    for leccion in lecciones:
        actual: list[_LineGroup] = []
        cuenta = 0
        for grupo in leccion:
            if actual and cuenta + len(grupo.lines) > LINES_PER_LESSON:
                troceadas.append(actual)
                actual, cuenta = [], 0
            actual.append(grupo)
            cuenta += len(grupo.lines)
        troceadas.append(actual)
    return troceadas


# --------------------------------------------------------------------------- #
# Conversión
# --------------------------------------------------------------------------- #


def convert_bjs_project(bjs: BjsProject) -> UntisProject:
    """Traduce un `BjsProject` ya abierto a `UntisProject` (ver docstring del módulo)."""
    problem = bjs.problem
    ids = _assign_ids(bjs)
    tareas = {int(t.id): t for t in problem.tasks}
    grid_ids = _grid_ids(bjs.school_weeks)

    def grid_of(week_index: int) -> str:
        return grid_ids[week_index] if 0 <= week_index < len(grid_ids) else DEFAULT_GRID_ID

    rows = lesson_rows(problem)
    need_default = not grid_ids or any(grid_of(r.school_week) == DEFAULT_GRID_ID for r in rows)
    time_grids = _time_grids(bjs, grid_ids, need_default)

    # --- departamentos (secciones) ------------------------------------- #
    secciones: dict[str, None] = {}
    for info in [*bjs.resource_info.values(), *bjs.subject_info.values()]:
        if info.get("section", "").strip():
            secciones[info["section"].strip()] = None
    departments = tuple(Department(id=s) for s in secciones)

    def section(info: dict[str, str]) -> str | None:
        return info.get("section", "").strip() or None

    # --- clases: tamaño y rejilla por las tareas que las requieren ------ #
    tamano: dict[str, int] = {}
    semanas: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for task in problem.tasks:
        for req in task.requirements:
            if req.tag.startswith("group#"):
                tamano[req.tag] = max(tamano.get(req.tag, 0), task.attribute("size", 0))
                semanas[req.tag][grid_of(task.attribute("school_week", -1))] += 1

    teachers: list[Teacher] = []
    classes: list[SchoolClass] = []
    rooms: list[Room] = []
    almuerzo = MinMax(min=1) if bjs.lunch_window is not None else MinMax()
    for res in sorted(problem.resources, key=lambda r: int(r.id)):
        rid = int(res.id)
        kind = ids.kind.get(rid)
        info = bjs.resource_info.get(rid, {})
        nombre = info.get("full_name", "").strip()
        if kind is EntityKind.TEACHER:
            teachers.append(
                Teacher(
                    id=ids.ids[rid],
                    name=nombre,
                    email=info.get("email", "").strip(),
                    department=section(info),
                    lunch_break=almuerzo,
                )
            )
        elif kind is EntityKind.CLASS:
            tag = next((t for t in sorted(res.tags) if t.startswith("group#")), "")
            conteo = semanas.get(tag)
            classes.append(
                SchoolClass(
                    id=ids.ids[rid],
                    name=nombre,
                    time_grid=conteo.most_common(1)[0][0] if conteo else time_grids[0].id,
                    home_room=ids.room_ref(info.get("home_room", "")),
                    department=section(info),
                    students=max(res.attribute("size", 0), tamano.get(tag, 0), 0),
                )
            )
        elif kind is EntityKind.ROOM:
            alternativa = ids.room_ref(info.get("alt_room", ""))
            asientos = res.attribute("seats", -1)
            rooms.append(
                Room(
                    id=ids.ids[rid],
                    name=nombre,
                    capacity=asientos if asientos >= 0 else None,
                    alternative_room=alternativa if alternativa != ids.ids[rid] else None,
                )
            )

    # --- materias -------------------------------------------------------- #
    nombres_materia: dict[str, None] = {}
    for task in problem.tasks:
        nombres_materia[task.name.split(_SUBJECT_SEP, 1)[0].strip()] = None
    for registrada in bjs.subjects:
        nombres_materia[registrada.strip()] = None
    subjects = tuple(
        Subject(
            id=s,
            name=bjs.subject_info.get(s, {}).get("full_name", "").strip(),
        )
        for s in nombres_materia
        if s
    )

    # --- lecciones -------------------------------------------------------- #
    lessons: list[Lesson] = []
    #: tarea -> [(nº de lección, índice de línea, aula fija de la línea)]
    lineas_de_tarea: defaultdict[int, list[tuple[int, int, str | None]]] = defaultdict(list)
    for numero, grupos in enumerate(_lesson_groups(rows, ids), start=1):
        principal = grupos[0].row
        duraciones = [tareas[t].duration for t in principal.task_ids]
        periodos = sum(duraciones)
        bloque = tuple(d for d in duraciones if d > 1)
        lineas: list[LessonLine] = []
        for grupo in grupos:
            for line in grupo.lines:
                for tid in grupo.row.task_ids:
                    lineas_de_tarea[tid].append((numero, len(lineas), line.room))
                lineas.append(line)
        lessons.append(
            Lesson(
                number=numero,
                lines=tuple(lineas),
                periods_per_week=periodos,
                time_grid=grid_of(principal.school_week),
                double_periods=double_periods_from_block(bloque, periodos),
                block=bloque,
            )
        )

    # --- deseos: disponibilidad bloqueada -> -3 --------------------------- #
    requests: dict[TimeRequest, None] = {}
    for rid, celdas in sorted(bjs.availability.items()):
        kind = ids.kind.get(rid)
        if kind is None:
            continue
        for dia, periodo in sorted(celdas):
            requests[
                TimeRequest(kind, ids.ids[rid], REQUEST_MIN, day=dia + 1, period=periodo + 1)
            ] = None

    # --- horario ------------------------------------------------------------ #
    timetables: tuple[Timetable, ...] = ()
    if bjs.solution is not None:
        segmentos = problem.grid.segments
        asignaciones: list[Assignment] = []
        colocadas: set[int] = set()
        for a in bjs.solution.assignments:
            tid = int(a.task_id)
            if tid not in tareas:
                continue
            inicio = int(a.start)
            dia_idx = next((i for i, s in enumerate(segmentos) if s.start <= inicio < s.end), None)
            if dia_idx is None:
                continue
            colocadas.add(tid)
            base = inicio - int(segmentos[dia_idx].start)
            elegidas = [
                ids.ids[int(r)] for r in a.resource_ids if ids.kind.get(int(r)) is EntityKind.ROOM
            ]
            for k, (numero, linea, aula_fija) in enumerate(lineas_de_tarea[tid]):
                aula = aula_fija or (elegidas[k % len(elegidas)] if elegidas else None)
                for off in range(tareas[tid].duration):
                    asignaciones.append(
                        Assignment(
                            lesson_number=numero,
                            line=linea,
                            day=dia_idx + 1,
                            period=base + off + 1,
                            room=aula,
                        )
                    )
        sin_colocar = sum(t.duration for tid, t in tareas.items() if tid not in colocadas)
        timetables = (
            Timetable(
                id=TIMETABLE_ID,
                name="Solución del .bjs",
                assignments=tuple(asignaciones),
                evaluation=Evaluation(
                    unplaced_periods=sin_colocar,
                    scores=tuple(
                        CriterionScore(p.source, p.amount, 1) for p in bjs.solution.penalties
                    ),
                ),
            ),
        )

    weighting = Weighting()
    if not bjs.options.avoid_same_subject_same_day:
        weighting = Weighting.from_dict({**weighting.as_dict(), "distribution_same_day": 0})

    nombre_proyecto = bjs.manifest.get("project_name", "")
    return UntisProject(
        school=SchoolInfo(name=nombre_proyecto if isinstance(nombre_proyecto, str) else ""),
        time_grids=time_grids,
        departments=departments,
        classes=tuple(classes),
        teachers=tuple(teachers),
        rooms=tuple(rooms),
        subjects=subjects,
        lessons=tuple(lessons),
        time_requests=tuple(requests),
        weighting=weighting,
        timetables=timetables,
    )
