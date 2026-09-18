"""Fachada Untis: la única puerta de la UI al producto (ADR-034).

Sin estado propio: cada método recibe la `UntisSession` y, si edita, sustituye
su proyecto con `session.apply(...)` (que apila deshacer). Las ediciones nunca
lanzan por datos inválidos: devuelven `EditResult` para que la UI marque la
celda en rojo, como en Untis. `optimize` tampoco lanza: el error va en el
`OptimizeOutcome`.
"""

from __future__ import annotations

import dataclasses
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import cast

from scheduling_platform.interop.bjs_legacy import load_bjs_as_project
from scheduling_platform.interop.gpu import read_gpu, write_gpu
from scheduling_platform.interop.rsp import load_rsp, save_rsp
from scheduling_platform.interop.xml import read_xml, write_xml
from scheduling_platform.untis_model import (
    TAB_OF_CRITERION,
    Assignment,
    EntityKind,
    HalfDay,
    Lesson,
    LessonLine,
    PeriodDef,
    PeriodKind,
    SchoolInfo,
    TimeGrid,
    TimeRequest,
    Timetable,
    UnspecifiedKind,
    UnspecifiedRequest,
    UntisProject,
    Weighting,
    WeightingTab,
    diagnose_data,
    hhmm_to_minutes,
    minutes_to_hhmm,
    slider_to_weight,
)
from scheduling_platform.untis_model.breaks import infer_breaks
from scheduling_platform.untis_model.evaluation import Evaluator
from scheduling_platform.untis_model.sessions import dominant_teaching_duration

from ..cancel import CancelToken
from .columns import (
    COLLECTION_OF,
    ENTITY_OF,
    MasterKind,
    ValueType,
    columns,
    format_value,
    parse_value,
)
from .session import UntisSession
from .texts import CRITERION_TEXTS, TAB_LABELS
from .views import (
    CriterionLine,
    DiagnosisItem,
    DiagnosisView,
    EditResult,
    EvaluationView,
    GridView,
    LessonLineRow,
    LessonRow,
    LoadSummary,
    MasterRow,
    MasterTable,
    MoveTarget,
    OptimizeOutcome,
    OptimizeProgress,
    OptimizeRequest,
    PeriodRow,
    RequestGrid,
    SliderView,
    TimetableCell,
    TimetableGrid,
    TimetableSummary,
    WeightingTabView,
)

#: Extensión del proyecto nativo.
PROJECT_SUFFIX = ".rsp"

_KIND_OF: dict[str, EntityKind] = {
    "class": EntityKind.CLASS,
    "teacher": EntityKind.TEACHER,
    "room": EntityKind.ROOM,
    "subject": EntityKind.SUBJECT,
}


def _entity_kind(kind: str) -> EntityKind:
    try:
        return _KIND_OF[kind]
    except KeyError as exc:
        raise ValueError(f"Tipo de entidad desconocido: {kind!r}") from exc


def _is_duty(lesson: Lesson) -> bool:
    return not any(line.classes or line.student_group for line in lesson.lines)


def _with_field[T](obj: T, field: str, value: object) -> T:
    """Copia de la entidad `obj` con `field` cambiado.

    Único punto dinámico de la Fachada: las cuadrículas editan campos por
    nombre (las columnas salen de los campos del propio modelo) y mypy no puede
    tipar `replace(obj, **{nombre: valor})`. El valor ya viene validado por
    `parse_value` y el `__post_init__` de la entidad revalida al construir.
    """
    replace: Callable[..., T] = dataclasses.replace
    return replace(obj, **{field: value})


def _clock(minutes: int) -> str:
    """Minutos desde medianoche -> `HH:MM`."""
    texto = minutes_to_hhmm(minutes)
    return f"{texto[:2]}:{texto[2:]}"


class UntisService:
    """Casos de uso del producto, en vocabulario Untis."""

    # ===================================================================== #
    # Ciclo de vida
    # ===================================================================== #

    def new(self, name: str = "") -> UntisSession:
        """Proyecto vacío."""
        return UntisSession(UntisProject(school=SchoolInfo(name=name)))

    def open(self, path: str | Path) -> UntisSession:
        """Abre `.rsp`, importa `.xml` / `.bjs` o una carpeta con archivos GPU."""
        ruta = Path(path)
        sufijo = ruta.suffix.lower()
        nativo = False
        if ruta.is_dir():
            proyecto = read_gpu(ruta)
            proyecto = infer_breaks(proyecto)
        elif sufijo == PROJECT_SUFFIX:
            proyecto = load_rsp(ruta)
            nativo = True
        elif sufijo == ".xml":
            proyecto = infer_breaks(read_xml(ruta))
        elif sufijo == ".bjs":
            proyecto = load_bjs_as_project(ruta)
        else:
            raise ValueError(f"Formato no reconocido: {ruta.name}")
        sesion = UntisSession(proyecto, path=ruta if nativo else None)
        if proyecto.timetables:
            sesion.active_timetable = proyecto.timetables[-1].id
        return sesion

    def save(self, session: UntisSession, path: str | Path | None = None) -> Path:
        """Guarda el proyecto como `.rsp` (el único formato nativo)."""
        destino = Path(path) if path is not None else session.path
        if destino is None:
            raise ValueError("Indica dónde guardar el proyecto")
        if destino.suffix.lower() != PROJECT_SUFFIX:
            destino = destino.with_suffix(PROJECT_SUFFIX)
        save_rsp(session.project, destino)
        session.mark_saved(destino)
        return destino

    def export_xml(self, session: UntisSession, path: str | Path) -> Path:
        destino = Path(path)
        write_xml(self._with_active_first(session), destino)
        return destino

    def export_gpu(
        self, session: UntisSession, directory: str | Path, timetable_id: str | None = None
    ) -> list[Path]:
        """Escribe GPU001-007 y GPU016; GPU001 con el horario activo (o el indicado)."""
        return write_gpu(
            session.project,
            Path(directory),
            timetable_id=timetable_id or session.active_timetable,
        )

    def undo(self, session: UntisSession) -> bool:
        return session.undo()

    def redo(self, session: UntisSession) -> bool:
        return session.redo()

    def _with_active_first(self, session: UntisSession) -> UntisProject:
        """El XmlInterface lleva un solo horario: el activo va primero."""
        p = session.project
        activo = p.timetable_by_id(session.active_timetable or "")
        if activo is None:
            return p
        otros = tuple(t for t in p.timetables if t.id != activo.id)
        return dataclasses.replace(p, timetables=(activo, *otros))

    # ===================================================================== #
    # Datos maestros
    # ===================================================================== #

    def master_table(self, session: UntisSession, kind: MasterKind) -> MasterTable:
        cols = columns(kind)
        entidades = getattr(session.project, COLLECTION_OF[kind])
        hallazgos: defaultdict[str, list[str]] = defaultdict(list)
        for issue in diagnose_data(session.project):
            if issue.entity_id:
                hallazgos[issue.entity_id].append(issue.message)
        filas = tuple(
            MasterRow(
                key=e.id,
                cells=tuple(format_value(getattr(e, c.field), c.value_type) for c in cols),
                issues=tuple(hallazgos.get(e.id, ())),
            )
            for e in entidades
        )
        refs = {
            c.field: tuple(x.id for x in getattr(session.project, c.reference))
            for c in cols
            if c.reference is not None
        }
        return MasterTable(kind, cols, filas, refs)

    def set_master_cell(
        self, session: UntisSession, kind: MasterKind, key: str, field: str, text: str
    ) -> EditResult:
        """Edita una celda; valida el valor y las referencias."""
        col = next((c for c in columns(kind) if c.field == field), None)
        if col is None or not col.editable:
            return EditResult.failure(f"La columna {field!r} no es editable")
        try:
            valor = parse_value(text, col.value_type)
        except ValueError as exc:
            return EditResult.failure(str(exc))
        if col.reference is not None and valor not in (None, ""):
            validos = {x.id for x in getattr(session.project, col.reference)}
            if valor not in validos:
                return EditResult.failure(f"{valor!r} no existe")
        coleccion = COLLECTION_OF[kind]
        actuales = getattr(session.project, coleccion)
        if not any(e.id == key for e in actuales):
            return EditResult.failure(f"No existe {key!r}")
        try:
            nuevas = tuple(_with_field(e, field, valor) if e.id == key else e for e in actuales)
            proyecto = _with_field(session.project, coleccion, nuevas)
        except (ValueError, TypeError) as exc:
            return EditResult.failure(str(exc))
        session.apply(proyecto, f"Editar {key}.{field}")
        return EditResult.success()

    def add_master(self, session: UntisSession, kind: MasterKind, entity_id: str) -> EditResult:
        ident = entity_id.strip()
        if not ident:
            return EditResult.failure("El nombre corto no puede estar vacío")
        coleccion = COLLECTION_OF[kind]
        actuales = getattr(session.project, coleccion)
        if any(e.id == ident for e in actuales):
            return EditResult.failure(f"{ident!r} ya existe")
        try:
            nueva = ENTITY_OF[kind](id=ident)
        except (ValueError, TypeError) as exc:
            return EditResult.failure(str(exc))
        proyecto = _with_field(session.project, coleccion, (*actuales, nueva))
        session.apply(proyecto, f"Añadir {ident}")
        return EditResult.success()

    def remove_master(self, session: UntisSession, kind: MasterKind, entity_id: str) -> EditResult:
        """Borra una entidad si ninguna lección la usa (como Untis, que avisa)."""
        usos = self._lesson_uses(session.project, kind, entity_id)
        if usos:
            return EditResult.failure(
                f"{entity_id!r} se usa en {len(usos)} lección(es): {', '.join(map(str, usos[:5]))}"
            )
        coleccion = COLLECTION_OF[kind]
        actuales = getattr(session.project, coleccion)
        restantes = tuple(e for e in actuales if e.id != entity_id)
        if len(restantes) == len(actuales):
            return EditResult.failure(f"No existe {entity_id!r}")
        session.apply(_with_field(session.project, coleccion, restantes), f"Borrar {entity_id}")
        return EditResult.success()

    @staticmethod
    def _lesson_uses(project: UntisProject, kind: MasterKind, entity_id: str) -> list[int]:
        usos: list[int] = []
        for le in project.lessons:
            for line in le.lines:
                if (
                    (kind is MasterKind.CLASSES and entity_id in line.classes)
                    or (kind is MasterKind.TEACHERS and line.teacher == entity_id)
                    or (kind is MasterKind.SUBJECTS and line.subject == entity_id)
                    or (kind is MasterKind.ROOMS and line.room == entity_id)
                    or (kind is MasterKind.STUDENT_GROUPS and line.student_group == entity_id)
                ):
                    usos.append(le.number)
                    break
        return usos

    # ===================================================================== #
    # Rejillas de tiempo
    # ===================================================================== #

    def grids(self, session: UntisSession) -> tuple[GridView, ...]:
        p = session.project
        return tuple(
            GridView(
                id=g.id,
                name=g.display_name,
                days=g.days,
                periods=self._period_rows(g.periods),
                classes=tuple(c.id for c in p.classes if c.time_grid == g.id),
            )
            for g in p.time_grids
        )

    @staticmethod
    def _period_rows(periods: tuple[PeriodDef, ...]) -> tuple[PeriodRow, ...]:
        return tuple(
            PeriodRow(
                number=p.number,
                start=_clock(p.start),
                end=_clock(p.end),
                is_break=p.kind is PeriodKind.BREAK,
                afternoon=p.half_day is HalfDay.AFTERNOON,
            )
            for p in sorted(periods, key=lambda x: x.number)
        )

    def set_period(
        self,
        session: UntisSession,
        grid_id: str,
        number: int,
        *,
        start: str | None = None,
        end: str | None = None,
        is_break: bool | None = None,
        afternoon: bool | None = None,
    ) -> EditResult:
        """Edita un período de una rejilla (horas `HH:MM`, recreo, tarde)."""
        p = session.project
        grid = p.grid_by_id.get(grid_id)
        if grid is None:
            return EditResult.failure(f"No existe la rejilla {grid_id!r}")
        periodo = grid.period(number)
        if periodo is None:
            return EditResult.failure(f"La rejilla {grid_id!r} no tiene el período {number}")
        try:
            nuevo = PeriodDef(
                number=periodo.number,
                start=hhmm_to_minutes(start.replace(":", "")) if start else periodo.start,
                end=hhmm_to_minutes(end.replace(":", "")) if end else periodo.end,
                kind=(
                    periodo.kind
                    if is_break is None
                    else (PeriodKind.BREAK if is_break else PeriodKind.LESSON)
                ),
                half_day=(
                    periodo.half_day
                    if afternoon is None
                    else (HalfDay.AFTERNOON if afternoon else HalfDay.MORNING)
                ),
                name=periodo.name,
            )
            nueva = dataclasses.replace(
                grid, periods=tuple(nuevo if x.number == number else x for x in grid.periods)
            )
        except ValueError as exc:
            return EditResult.failure(str(exc))
        grids = tuple(nueva if g.id == grid_id else g for g in p.time_grids)
        session.apply(dataclasses.replace(p, time_grids=grids), f"Editar período {number}")
        return EditResult.success()

    # ===================================================================== #
    # Lecciones
    # ===================================================================== #

    def lessons(
        self,
        session: UntisSession,
        *,
        class_id: str | None = None,
        teacher_id: str | None = None,
        subject_id: str | None = None,
    ) -> tuple[LessonRow, ...]:
        p = session.project
        colocadas = self._placed_counts(p, session.active_timetable)
        filas: list[LessonRow] = []
        for le in p.lessons:
            if class_id is not None and class_id not in le.classes:
                continue
            if teacher_id is not None and teacher_id not in le.teachers:
                continue
            if subject_id is not None and subject_id not in le.subjects:
                continue
            filas.append(self._lesson_row(le, colocadas.get(le.number, 0)))
        return tuple(filas)

    @staticmethod
    def _lesson_row(le: Lesson, placed: int) -> LessonRow:
        return LessonRow(
            number=le.number,
            lines=tuple(
                LessonLineRow(
                    index=i,
                    teacher=line.teacher or "",
                    subject=line.subject,
                    classes=", ".join(line.classes),
                    student_group=line.student_group or "",
                    room=line.room or "",
                )
                for i, line in enumerate(le.lines)
            ),
            periods_per_week=le.periods_per_week,
            placed=placed,
            double_periods=format_value(le.double_periods, ValueType.MINMAX),
            block=",".join(map(str, le.block)),
            time_grid=le.time_grid,
            fixed=le.fixed,
            ignore=le.ignore,
            not_same_day=le.not_same_day,
            weekly_value=le.weekly_value,
        )

    @staticmethod
    def _placed_counts(project: UntisProject, timetable_id: str | None) -> dict[int, int]:
        tt = project.timetable_by_id(timetable_id or "")
        if tt is None:
            return {}
        celdas: defaultdict[int, set[tuple[int, int]]] = defaultdict(set)
        for a in tt.assignments:
            if a.line == 0:
                celdas[a.lesson_number].add(a.slot)
        return {n: len(c) for n, c in celdas.items()}

    def load_summary(self, session: UntisSession, kind: str, entity_id: str) -> LoadSummary:
        """Suma de períodos de una clase o profesor frente a la capacidad de su rejilla."""
        p = session.project
        colocadas = self._placed_counts(p, session.active_timetable)
        if kind == "class":
            lecciones = p.lessons_of_class(entity_id)
            grid = p.grid_for_class(entity_id)
        elif kind == "teacher":
            lecciones = p.lessons_of_teacher(entity_id)
            usos = Counter(le.time_grid for le in lecciones)
            grid = p.grid_by_id.get(usos.most_common(1)[0][0]) if usos else None
        else:
            raise ValueError(f"Tipo de entidad sin carga: {kind!r}")
        activas = [le for le in lecciones if not le.ignore]
        return LoadSummary(
            entity_kind=kind,
            entity_id=entity_id,
            periods=sum(le.periods_per_week for le in activas),
            placed=sum(min(colocadas.get(le.number, 0), le.periods_per_week) for le in activas),
            capacity=len(grid.slots()) if grid is not None else 0,
        )

    def add_lesson(
        self,
        session: UntisSession,
        *,
        subject: str,
        teacher: str | None,
        classes: tuple[str, ...],
        periods: int,
        time_grid: str | None = None,
    ) -> EditResult:
        """Añade una lección de una línea; `message` devuelve su número."""
        p = session.project
        if subject not in p.subject_by_id:
            return EditResult.failure(f"La materia {subject!r} no existe")
        if teacher is not None and teacher not in p.teacher_by_id:
            return EditResult.failure(f"El profesor {teacher!r} no existe")
        faltan = [c for c in classes if c not in p.class_by_id]
        if faltan:
            return EditResult.failure(f"Clases inexistentes: {', '.join(faltan)}")
        rejilla = time_grid
        if rejilla is None and classes:
            clase = p.class_by_id[classes[0]]
            rejilla = clase.time_grid
        numero = self._next_lesson_number(p)
        try:
            nueva = Lesson(
                number=numero,
                lines=(LessonLine(subject=subject, teacher=teacher, classes=classes),),
                periods_per_week=periods,
                time_grid=rejilla or (p.time_grids[0].id if p.time_grids else ""),
            )
        except ValueError as exc:
            return EditResult.failure(str(exc))
        session.apply(
            dataclasses.replace(p, lessons=(*p.lessons, nueva)), f"Añadir lección {numero}"
        )
        return EditResult.success(str(numero))

    @staticmethod
    def _next_lesson_number(project: UntisProject) -> int:
        return max((le.number for le in project.lessons), default=0) + 1

    def _replace_lesson(
        self, session: UntisSession, number: int, build: Callable[[Lesson], Lesson], label: str
    ) -> EditResult:
        p = session.project
        actual = p.lesson_by_number.get(number)
        if actual is None:
            return EditResult.failure(f"No existe la lección {number}")
        try:
            nueva = build(actual)
        except (ValueError, TypeError) as exc:
            return EditResult.failure(str(exc))
        lecciones = tuple(nueva if le.number == number else le for le in p.lessons)
        session.apply(dataclasses.replace(p, lessons=lecciones), label)
        return EditResult.success()

    _LESSON_FIELDS: dict[str, ValueType] = {  # noqa: RUF012 - tabla de solo lectura
        "periods_per_week": ValueType.INT,
        "double_periods": ValueType.MINMAX,
        "block": ValueType.LIST,
        "time_grid": ValueType.TEXT,
        "fixed": ValueType.BOOL,
        "ignore": ValueType.BOOL,
        "not_same_day": ValueType.BOOL,
        "weekly_value": ValueType.TEXT,
        "sequence_after": ValueType.OPT_TEXT,
    }

    def set_lesson_field(
        self, session: UntisSession, number: int, field: str, text: str
    ) -> EditResult:
        """Edita una columna de la lección (Per/sem, Dobles, Bloque, Fijar, ...)."""
        tipo = self._LESSON_FIELDS.get(field)
        if tipo is None:
            return EditResult.failure(f"La columna {field!r} no es editable")
        try:
            valor = parse_value(text, tipo)
            if field == "block":
                valor = tuple(int(x) for x in cast(tuple[str, ...], valor))
            elif field == "weekly_value":
                valor = float(str(valor).replace(",", ".") or 0)
        except ValueError as exc:
            return EditResult.failure(str(exc))
        if field == "time_grid" and valor not in session.project.grid_by_id:
            return EditResult.failure(f"La rejilla {valor!r} no existe")
        return self._replace_lesson(
            session,
            number,
            lambda le: _with_field(le, field, valor),
            f"Lección {number}: {field}",
        )

    _LINE_FIELDS: dict[str, ValueType] = {  # noqa: RUF012 - tabla de solo lectura
        "teacher": ValueType.OPT_TEXT,
        "subject": ValueType.TEXT,
        "classes": ValueType.LIST,
        "student_group": ValueType.OPT_TEXT,
        "room": ValueType.OPT_TEXT,
        "alternative_room": ValueType.OPT_TEXT,
    }

    _LINE_REFS: dict[str, str] = {  # noqa: RUF012 - tabla de solo lectura
        "teacher": "teacher_by_id",
        "subject": "subject_by_id",
        "student_group": "student_group_by_id",
        "room": "room_by_id",
        "alternative_room": "room_by_id",
    }

    def set_line_field(
        self, session: UntisSession, number: int, index: int, field: str, text: str
    ) -> EditResult:
        """Edita una línea del acople (profesor, materia, clases, aula...)."""
        tipo = self._LINE_FIELDS.get(field)
        if tipo is None:
            return EditResult.failure(f"La columna {field!r} no es editable")
        try:
            valor = parse_value(text, tipo)
        except ValueError as exc:
            return EditResult.failure(str(exc))
        p = session.project
        if field == "classes":
            faltan = [c for c in cast(tuple[str, ...], valor) if c not in p.class_by_id]
            if faltan:
                return EditResult.failure(f"Clases inexistentes: {', '.join(faltan)}")
        elif valor is not None and field in self._LINE_REFS:
            if valor not in getattr(p, self._LINE_REFS[field]):
                return EditResult.failure(f"{valor!r} no existe")

        def construir(le: Lesson) -> Lesson:
            if not 0 <= index < len(le.lines):
                raise ValueError(f"La lección {number} no tiene la línea {index}")
            linea = _with_field(le.lines[index], field, valor)
            return dataclasses.replace(
                le, lines=tuple(linea if i == index else x for i, x in enumerate(le.lines))
            )

        return self._replace_lesson(session, number, construir, f"Lección {number}: {field}")

    def add_line(self, session: UntisSession, number: int) -> EditResult:
        """Acopla una línea nueva (copia de la última, sin profesor ni aula)."""

        def construir(le: Lesson) -> Lesson:
            ultima = le.lines[-1]
            nueva = dataclasses.replace(ultima, teacher=None, room=None, alternative_room=None)
            return dataclasses.replace(le, lines=(*le.lines, nueva))

        return self._replace_lesson(session, number, construir, f"Acoplar en {number}")

    def remove_line(self, session: UntisSession, number: int, index: int) -> EditResult:
        def construir(le: Lesson) -> Lesson:
            if len(le.lines) == 1:
                raise ValueError("Una lección necesita al menos una línea")
            if not 0 <= index < len(le.lines):
                raise ValueError(f"La lección {number} no tiene la línea {index}")
            return dataclasses.replace(
                le, lines=tuple(x for i, x in enumerate(le.lines) if i != index)
            )

        resultado = self._replace_lesson(session, number, construir, f"Desacoplar en {number}")
        if resultado.ok:
            self._drop_line_assignments(session, number, index)
        return resultado

    def _drop_line_assignments(self, session: UntisSession, number: int, index: int) -> None:
        """Renumera las asignaciones de las líneas tras quitar la línea `index`."""
        p = session.project
        horarios = []
        for tt in p.timetables:
            nuevas = tuple(
                dataclasses.replace(a, line=a.line - 1) if a.line > index else a
                for a in tt.assignments
                if not (a.lesson_number == number and a.line == index)
            )
            horarios.append(dataclasses.replace(tt, assignments=nuevas))
        session.project = dataclasses.replace(p, timetables=tuple(horarios))

    def remove_lesson(self, session: UntisSession, number: int) -> EditResult:
        p = session.project
        if number not in p.lesson_by_number:
            return EditResult.failure(f"No existe la lección {number}")
        horarios = tuple(
            dataclasses.replace(
                tt, assignments=tuple(a for a in tt.assignments if a.lesson_number != number)
            )
            for tt in p.timetables
        )
        proyecto = dataclasses.replace(
            p,
            lessons=tuple(le for le in p.lessons if le.number != number),
            timetables=horarios,
        )
        session.apply(proyecto, f"Borrar lección {number}")
        return EditResult.success()

    # ===================================================================== #
    # Deseos de tiempo
    # ===================================================================== #

    def request_grid(self, session: UntisSession, kind: str, entity_id: str) -> RequestGrid:
        p = session.project
        ek = _entity_kind(kind)
        grid = self._grid_of(p, kind, entity_id)
        dias = grid.days if grid is not None else (1, 2, 3, 4, 5)
        periodos = (
            tuple(x.number for x in sorted(grid.periods, key=lambda x: x.number))
            if grid is not None
            else ()
        )
        recreos = (
            tuple(x.number for x in grid.periods if x.kind is PeriodKind.BREAK)
            if grid is not None
            else ()
        )
        valores: dict[tuple[int, int], int] = {}
        por_dia: dict[int, int] = {}
        for r in p.requests_for(ek, entity_id):
            if r.day is not None and r.period is not None:
                valores[(r.day, r.period)] = r.value
            elif r.day is not None:
                por_dia[r.day] = r.value
        return RequestGrid(kind, entity_id, dias, periodos, valores, por_dia, recreos)

    def set_request(
        self,
        session: UntisSession,
        kind: str,
        entity_id: str,
        day: int | None,
        period: int | None,
        value: int,
    ) -> EditResult:
        """Fija un deseo -3..+3 en una celda, un día o un período (0 lo borra)."""
        p = session.project
        try:
            ek = _entity_kind(kind)
        except ValueError as exc:
            return EditResult.failure(str(exc))
        otros = tuple(
            r
            for r in p.time_requests
            if not (
                r.entity_kind is ek
                and r.entity_id == entity_id
                and r.day == day
                and r.period == period
            )
        )
        if value == 0:
            nuevos = otros
        else:
            try:
                nuevos = (*otros, TimeRequest(ek, entity_id, value, day=day, period=period))
            except ValueError as exc:
                return EditResult.failure(str(exc))
        session.apply(dataclasses.replace(p, time_requests=nuevos), f"Deseo de {entity_id}")
        return EditResult.success()

    def unspecified_requests(
        self, session: UntisSession, kind: str, entity_id: str
    ) -> tuple[tuple[str, int], ...]:
        """Deseos no especificados de una entidad: `(tipo, cantidad)`.

        Tipos: `free_day`, `free_morning`, `free_afternoon` ("2 tardes libres").
        """
        ek = _entity_kind(kind)
        return tuple(
            (r.kind.value, r.count) for r in session.project.unspecified_for(ek, entity_id)
        )

    def set_unspecified(
        self, session: UntisSession, kind: str, entity_id: str, request_kind: str, count: int
    ) -> EditResult:
        """Fija "N días/mañanas/tardes libres" de una entidad (0 lo borra)."""
        p = session.project
        try:
            ek = _entity_kind(kind)
            tipo = UnspecifiedKind(request_kind)
        except ValueError as exc:
            return EditResult.failure(str(exc))
        otros = tuple(
            r
            for r in p.unspecified_requests
            if not (r.entity_kind is ek and r.entity_id == entity_id and r.kind is tipo)
        )
        if count == 0:
            nuevos = otros
        else:
            try:
                nuevos = (*otros, UnspecifiedRequest(ek, entity_id, tipo, count))
            except ValueError as exc:
                return EditResult.failure(str(exc))
        session.apply(
            dataclasses.replace(p, unspecified_requests=nuevos),
            f"Deseo no especificado de {entity_id}",
        )
        return EditResult.success()

    @staticmethod
    def _grid_of(project: UntisProject, kind: str, entity_id: str) -> TimeGrid | None:
        """Rejilla propia de la entidad (la de la clase; la más usada si no)."""
        if kind == "class":
            return project.grid_for_class(entity_id)
        if kind == "teacher":
            usos = Counter(le.time_grid for le in project.lessons_of_teacher(entity_id))
            if usos:
                return project.grid_by_id.get(usos.most_common(1)[0][0])
        return project.time_grids[0] if project.time_grids else None

    # ===================================================================== #
    # Datos del colegio
    # ===================================================================== #

    #: Campos editables de los datos del colegio: `campo -> (español, alemán)`.
    SCHOOL_FIELDS: dict[str, tuple[str, str]] = {  # noqa: RUF012 - tabla de solo lectura
        "name": ("Nombre del colegio", "Schulname"),
        "school_year_begin": ("Inicio del curso (AAAAMMDD)", "Schuljahresbeginn (JJJJMMTT)"),
        "school_year_end": ("Fin del curso (AAAAMMDD)", "Schuljahresende (JJJJMMTT)"),
        "header1": ("Encabezado 1", "Kopfzeile 1"),
        "header2": ("Encabezado 2", "Kopfzeile 2"),
        "footer": ("Pie de página", "Fußzeile"),
        "term_name": ("Nombre del período", "Periodenname"),
    }

    def school_info(self, session: UntisSession) -> tuple[tuple[str, str], ...]:
        """Datos del colegio editables: `(campo, valor)`."""
        info = session.project.school
        return tuple((campo, str(getattr(info, campo))) for campo in self.SCHOOL_FIELDS)

    def set_school_field(self, session: UntisSession, field: str, value: str) -> EditResult:
        if field not in self.SCHOOL_FIELDS:
            return EditResult.failure(f"Campo desconocido: {field!r}")
        texto = value.strip()
        if (
            field in ("school_year_begin", "school_year_end")
            and texto
            and (len(texto) != 8 or not texto.isdigit())
        ):
            return EditResult.failure("La fecha debe tener el formato AAAAMMDD")
        p = session.project
        session.apply(
            dataclasses.replace(p, school=_with_field(p.school, field, texto)),
            f"Datos del colegio: {field}",
        )
        return EditResult.success()

    # ===================================================================== #
    # Ponderación
    # ===================================================================== #

    def weighting_tabs(self, session: UntisSession) -> tuple[WeightingTabView, ...]:
        w = session.project.weighting
        por_tab: defaultdict[WeightingTab, list[SliderView]] = defaultdict(list)
        for criterio in Weighting.criteria():
            es, de, ayuda = CRITERION_TEXTS.get(criterio, (criterio, criterio, ""))
            valor = w.as_dict()[criterio]
            por_tab[TAB_OF_CRITERION[criterio]].append(
                SliderView(criterio, es, de, ayuda, valor, slider_to_weight(valor))
            )
        return tuple(
            WeightingTabView(
                tab=tab.value,
                label=TAB_LABELS[tab.value][0],
                label_de=TAB_LABELS[tab.value][1],
                sliders=tuple(por_tab.get(tab, ())),
            )
            for tab in WeightingTab
        )

    def set_slider(self, session: UntisSession, criterion: str, value: int) -> EditResult:
        w = session.project.weighting
        if criterion not in Weighting.criteria():
            return EditResult.failure(f"Criterio desconocido: {criterion!r}")
        try:
            nueva = _with_field(w, criterion, value)
        except ValueError as exc:
            return EditResult.failure(str(exc))
        session.apply(session.project.with_weighting(nueva), f"Ponderación: {criterion}")
        aviso = ""
        if value == 5 and sum(1 for v in nueva.as_dict().values() if v == 5) > 1:
            aviso = "Más de un criterio en 5: el 5 conviene usarlo de uno en uno."
        return EditResult.success(aviso)

    # ===================================================================== #
    # Horarios, evaluación y diagnóstico
    # ===================================================================== #

    def timetables(self, session: UntisSession) -> tuple[TimetableSummary, ...]:
        ev = Evaluator(session.project)
        resumen = []
        for tt in session.project.timetables:
            e = ev.evaluate(tt)
            resumen.append(
                TimetableSummary(
                    tt.id,
                    tt.display_name,
                    e.total,
                    e.unplaced_periods,
                    e.clashes,
                    tt.id == session.active_timetable,
                )
            )
        return tuple(resumen)

    def set_active_timetable(self, session: UntisSession, timetable_id: str) -> EditResult:
        if session.project.timetable_by_id(timetable_id) is None:
            return EditResult.failure(f"No existe el horario {timetable_id!r}")
        session.active_timetable = timetable_id
        return EditResult.success()

    def remove_timetable(self, session: UntisSession, timetable_id: str) -> EditResult:
        p = session.project
        if p.timetable_by_id(timetable_id) is None:
            return EditResult.failure(f"No existe el horario {timetable_id!r}")
        restantes = tuple(t for t in p.timetables if t.id != timetable_id)
        session.apply(dataclasses.replace(p, timetables=restantes), f"Borrar {timetable_id}")
        return EditResult.success()

    def _timetable(self, session: UntisSession, timetable_id: str | None) -> Timetable | None:
        return session.project.timetable_by_id(timetable_id or session.active_timetable or "")

    def evaluation(
        self, session: UntisSession, timetable_id: str | None = None
    ) -> EvaluationView | None:
        tt = self._timetable(session, timetable_id)
        if tt is None:
            return None
        return self._evaluation_view(session.project, tt)

    @staticmethod
    def _evaluation_view(project: UntisProject, tt: Timetable) -> EvaluationView:
        e = Evaluator(project).evaluate(tt)
        w = project.weighting.as_dict()
        lineas = tuple(
            CriterionLine(
                criterion=s.criterion,
                label=CRITERION_TEXTS.get(s.criterion, (s.criterion, "", ""))[0],
                tab=TAB_OF_CRITERION[s.criterion].value,
                slider=w[s.criterion],
                weight=s.weight,
                violations=s.violations,
                points=s.points,
            )
            for s in e.by_contribution()
        )
        return EvaluationView(tt.id, e.total, e.soft_points, e.unplaced_periods, e.clashes, lineas)

    def diagnosis(self, session: UntisSession, timetable_id: str | None = None) -> DiagnosisView:
        """Árbol de Diagnóstico: datos de entrada y, si hay horario, sus violaciones."""
        p = session.project
        items: list[DiagnosisItem] = [
            DiagnosisItem(
                branch="datos",
                group=i.code,
                severity=i.severity.value,
                message=i.message,
                entity_kind=i.entity_kind.value if i.entity_kind else "",
                entity_id=i.entity_id,
                lesson=i.lesson_number,
            )
            for i in diagnose_data(p)
        ]
        tt = self._timetable(session, timetable_id)
        if tt is not None:
            rep = Evaluator(p).report(tt)
            for c in rep.clashes:
                items.append(
                    DiagnosisItem(
                        branch="horario",
                        group=f"choque_{c.kind}",
                        severity="error",
                        message=c.message,
                        entity_id=c.entity_id,
                        lesson=c.lessons[0] if c.lessons else None,
                        day=c.day,
                    )
                )
            for numero, falta in rep.unplaced:
                items.append(
                    DiagnosisItem(
                        branch="horario",
                        group="no_colocados",
                        severity="error",
                        message=f"La lección {numero} tiene {falta} período(s) sin colocar.",
                        amount=falta,
                        lesson=numero,
                    )
                )
            pesos = {s.criterion: s.weight for s in rep.evaluation.scores}
            for v in sorted(
                rep.violations, key=lambda v: (-pesos.get(v.criterion, 0), v.criterion)
            ):
                items.append(
                    DiagnosisItem(
                        branch="horario",
                        group=v.criterion,
                        severity="warning",
                        message=v.message,
                        amount=v.amount,
                        entity_kind=v.entity_kind.value if v.entity_kind else "",
                        entity_id=v.entity_id,
                        lesson=v.lesson,
                        day=v.day,
                        period=v.period,
                    )
                )
        return DiagnosisView(tuple(items))

    # ===================================================================== #
    # Optimización
    # ===================================================================== #

    def optimize(
        self,
        session: UntisSession,
        request: OptimizeRequest,
        *,
        on_progress: Callable[[OptimizeProgress], None] | None = None,
        cancel: CancelToken | None = None,
    ) -> OptimizeOutcome:
        """Ejecuta una estrategia y añade el horario resultante. Nunca lanza."""
        from scheduling_platform.bridge.optimize import run_strategy
        from scheduling_platform.heuristic import Progress, Strategy

        t0 = time.perf_counter()
        try:
            estrategia = Strategy(request.strategy)
        except ValueError:
            return OptimizeOutcome(False, "error", f"Estrategia desconocida: {request.strategy}")
        p = session.project
        if not p.active_lessons:
            return OptimizeOutcome(False, "error", "El proyecto no tiene lecciones")
        errores = [i for i in diagnose_data(p) if i.is_error]
        if errores:
            return OptimizeOutcome(
                False,
                "error",
                f"Corrige antes {len(errores)} error(es) de datos (ver Diagnóstico).",
            )
        referencia = self._timetable(session, None)

        def progreso(evento: Progress) -> None:
            if on_progress is not None:
                on_progress(
                    OptimizeProgress(
                        evento.phase,
                        evento.iteration,
                        evento.current,
                        evento.best,
                        evento.unplaced,
                        evento.elapsed,
                    )
                )

        nuevo_id = self._new_timetable_id(p, estrategia.value)
        try:
            resultado = run_strategy(
                p,
                estrategia,
                reference=referencia,
                seed=request.seed,
                time_limit=request.time_limit,
                placement_share=request.placement_share,
                optimize_teachers=request.optimize_teachers,
                polish=request.polish,
                timetable_id=nuevo_id,
                on_progress=progreso,
                should_stop=cancel.is_cancelled if cancel is not None else None,
            )
        except Exception as exc:
            return OptimizeOutcome(
                False, "error", f"Error al optimizar: {exc}", elapsed=time.perf_counter() - t0
            )

        nombre = request.name or f"Estrategia {estrategia.value} ({nuevo_id})"
        tt = dataclasses.replace(resultado.timetable, id=nuevo_id, name=nombre)
        session.apply(p.with_timetable(tt), f"Optimizar ({estrategia.value})")
        session.active_timetable = nuevo_id
        vista = self._evaluation_view(session.project, tt)
        return OptimizeOutcome(
            True,
            "cancelled" if resultado.cancelled else "solved",
            f"Número de evaluación {vista.total}: {vista.unplaced_periods} sin colocar, "
            f"{vista.clashes} choque(s).",
            timetable_id=nuevo_id,
            evaluation=vista,
            elapsed=time.perf_counter() - t0,
            log=tuple(
                f"{s.phase}: {s.total} ({s.elapsed:.1f} s) {s.detail}" for s in resultado.steps
            ),
        )

    def adopt_timetable(
        self, session: UntisSession, source: UntisSession, timetable_id: str
    ) -> EditResult:
        """Incorpora a `session` un horario calculado sobre una copia (`source`).

        La UI optimiza en un hilo sobre una sesión-instantánea para no competir
        con el hilo de la interfaz; al terminar, este método lleva el horario a
        la sesión real (se puede deshacer).
        """
        tt = source.project.timetable_by_id(timetable_id)
        if tt is None:
            return EditResult.failure(f"No existe el horario {timetable_id!r}")
        if session.project.lessons != source.project.lessons:
            return EditResult.failure("Las lecciones cambiaron durante la optimización")
        session.apply(session.project.with_timetable(tt), f"Optimizar ({tt.display_name})")
        session.active_timetable = tt.id
        return EditResult.success()

    def snapshot(self, session: UntisSession) -> UntisSession:
        """Copia independiente de la sesión (misma instantánea del proyecto)."""
        copia = UntisSession(session.project, path=session.path)
        copia.active_timetable = session.active_timetable
        return copia

    @staticmethod
    def _new_timetable_id(project: UntisProject, prefix: str) -> str:
        n = 1
        existentes = {t.id for t in project.timetables}
        while f"{prefix}-{n}" in existentes:
            n += 1
        return f"{prefix}-{n}"

    # ===================================================================== #
    # Horario de una entidad y Diálogo de planificación
    # ===================================================================== #

    def timetable_grid(
        self, session: UntisSession, kind: str, entity_id: str, timetable_id: str | None = None
    ) -> TimetableGrid:
        p = session.project
        tt = self._timetable(session, timetable_id)
        grid = self._grid_of(p, kind, entity_id)
        lecciones = p.lesson_by_number
        colores = {s.id: s.back_color for s in p.subjects}
        choques: set[tuple[int, int, int]] = set()
        celdas: list[TimetableCell] = []
        sin: list[tuple[int, int]] = []
        if tt is not None:
            rep = Evaluator(p).report(tt)
            for c in rep.clashes:
                for n in c.lessons:
                    choques.add((n, c.day, 0))
            por_celda: defaultdict[tuple[int, int, int], list[Assignment]] = defaultdict(list)
            for a in tt.assignments:
                por_celda[(a.lesson_number, a.day, a.period)].append(a)
            for (numero, dia, periodo), asigs in sorted(por_celda.items()):
                le = lecciones.get(numero)
                if le is None or not self._involves(le, kind, entity_id, asigs):
                    continue
                celdas.append(
                    TimetableCell(
                        day=dia,
                        period=periodo,
                        lesson=numero,
                        subject=le.subjects[0] if le.subjects else "",
                        teachers=le.teachers,
                        classes=le.classes,
                        rooms=tuple(dict.fromkeys(a.room for a in asigs if a.room)),
                        fixed=le.fixed or any(a.fixed for a in asigs),
                        conflict=(numero, dia, 0) in choques,
                        color=colores.get(le.subjects[0], "") if le.subjects else "",
                    )
                )
            sin = [
                (n, f)
                for n, f in rep.unplaced
                if n in lecciones and self._involves(lecciones[n], kind, entity_id, [])
            ]
        titulo = self._display(p, kind, entity_id)
        return TimetableGrid(
            entity_kind=kind,
            entity_id=entity_id,
            title=titulo,
            days=grid.days if grid is not None else (1, 2, 3, 4, 5),
            periods=self._period_rows(grid.periods) if grid is not None else (),
            cells=tuple(celdas),
            unplaced=tuple(sin),
        )

    @staticmethod
    def _involves(le: Lesson, kind: str, entity_id: str, asigs: list[Assignment]) -> bool:
        if kind == "class":
            return entity_id in le.classes
        if kind == "teacher":
            return entity_id in le.teachers
        if kind == "room":
            return any(a.room == entity_id for a in asigs) or any(
                line.room == entity_id for line in le.lines
            )
        if kind == "subject":
            return entity_id in le.subjects
        return False

    @staticmethod
    def _display(project: UntisProject, kind: str, entity_id: str) -> str:
        indices: dict[str, dict[str, object]] = {
            "class": dict(project.class_by_id),
            "teacher": dict(project.teacher_by_id),
            "room": dict(project.room_by_id),
            "subject": dict(project.subject_by_id),
        }
        entidad = indices.get(kind, {}).get(entity_id)
        nombre = getattr(entidad, "display_name", entity_id) if entidad is not None else entity_id
        return f"{entity_id} - {nombre}" if nombre != entity_id else entity_id

    # --- planificación manual ------------------------------------------------ #

    def move_targets(
        self,
        session: UntisSession,
        lesson: int,
        cell: tuple[int, int] | None,
        timetable_id: str | None = None,
    ) -> tuple[MoveTarget, ...]:
        """Para cada celda posible: ¿se puede soltar ahí la sesión, y por qué no?

        `cell` es la celda actual de la sesión (`None` = sesión sin colocar). Solo
        se ofrecen celdas de la misma duración (`untis_model.sessions`).
        """
        p = session.project
        le = p.lesson_by_number.get(lesson)
        tt = self._timetable(session, timetable_id)
        grid = p.grid_by_id.get(le.time_grid) if le is not None else None
        if le is None or grid is None:
            return ()
        duracion = self._session_duration(grid, cell)
        ocupacion = self._occupancy(p, tt, excluir=(lesson, cell))
        propias = self._lesson_cells(tt, lesson)
        vetos = self._hard_blocks(p, le)
        objetivos: list[MoveTarget] = []
        for dia in sorted(grid.days):
            for per in grid.teaching_periods:
                if per.duration != duracion:
                    continue
                destino = (dia, per.number)
                motivo = ""
                if destino != cell and destino in propias:
                    motivo = "la lección ya está en esa celda"
                elif destino in vetos:
                    motivo = "deseo imposible (-3)"
                elif le.fixed and cell is not None and destino != cell:
                    motivo = "lección fijada"
                else:
                    motivo = self._clash_reason(ocupacion, le, dia, per.start, per.end)
                objetivos.append(MoveTarget(dia, per.number, not motivo, motivo))
        return tuple(objetivos)

    def move_delta(
        self,
        session: UntisSession,
        lesson: int,
        source: tuple[int, int] | None,
        target: tuple[int, int],
        timetable_id: str | None = None,
    ) -> int | None:
        """Cambio exacto del número de evaluación si la sesión va a `target`."""
        tt = self._timetable(session, timetable_id)
        if tt is None:
            return None
        nuevo = self._moved(session.project, tt, lesson, source, target)
        if nuevo is None:
            return None
        ev = Evaluator(session.project)
        return ev.evaluate(nuevo).total - ev.evaluate(tt).total

    def move_session(
        self,
        session: UntisSession,
        lesson: int,
        source: tuple[int, int] | None,
        target: tuple[int, int],
        timetable_id: str | None = None,
    ) -> EditResult:
        """Mueve (o coloca, si `source` es `None`) una sesión, comprobando las duras."""
        destino = next(
            (
                t
                for t in self.move_targets(session, lesson, source, timetable_id)
                if (t.day, t.period) == target
            ),
            None,
        )
        if destino is None:
            return EditResult.failure("Esa celda no es de la duración de la sesión")
        if not destino.feasible:
            return EditResult.failure(destino.reason)
        tt = self._timetable(session, timetable_id)
        if tt is None:
            return EditResult.failure("No hay horario activo")
        nuevo = self._moved(session.project, tt, lesson, source, target)
        if nuevo is None:
            return EditResult.failure("No se pudo mover la sesión")
        session.apply(session.project.with_timetable(nuevo), f"Mover lección {lesson}")
        return EditResult.success()

    def unplace_session(
        self,
        session: UntisSession,
        lesson: int,
        cell: tuple[int, int],
        timetable_id: str | None = None,
    ) -> EditResult:
        """Desprograma una sesión (F7 en el Diálogo de planificación)."""
        tt = self._timetable(session, timetable_id)
        if tt is None:
            return EditResult.failure("No hay horario activo")
        le = session.project.lesson_by_number.get(lesson)
        if le is not None and le.fixed:
            return EditResult.failure("Lección fijada: desfíjala antes")
        quedan = tuple(
            a for a in tt.assignments if not (a.lesson_number == lesson and a.slot == cell)
        )
        if len(quedan) == len(tt.assignments):
            return EditResult.failure("La lección no está en esa celda")
        nuevo = dataclasses.replace(tt, assignments=quedan)
        session.apply(session.project.with_timetable(nuevo), f"Desprogramar lección {lesson}")
        return EditResult.success()

    def set_fixed(self, session: UntisSession, lesson: int, fixed: bool) -> EditResult:
        return self._replace_lesson(
            session,
            lesson,
            lambda le: dataclasses.replace(le, fixed=fixed),
            f"{'Fijar' if fixed else 'Desfijar'} lección {lesson}",
        )

    def swap_sessions(
        self,
        session: UntisSession,
        a: tuple[int, tuple[int, int]],
        b: tuple[int, tuple[int, int]],
        timetable_id: str | None = None,
    ) -> EditResult:
        """Intercambia dos sesiones de la misma duración, si ambas caben."""
        tt = self._timetable(session, timetable_id)
        if tt is None:
            return EditResult.failure("No hay horario activo")
        (la, ca), (lb, cb) = a, b
        p = session.project
        paso = self._moved(p, tt, la, ca, cb)
        if paso is None:
            return EditResult.failure("No se pudo intercambiar")
        final = self._moved(p, paso, lb, cb, ca)
        if final is None:
            return EditResult.failure("No se pudo intercambiar")
        rep = Evaluator(p).report(final)
        antes = Evaluator(p).report(tt)
        if len(rep.clashes) > len(antes.clashes):
            return EditResult.failure("El intercambio provoca un choque")
        session.apply(p.with_timetable(final), f"Intercambiar {la} y {lb}")
        return EditResult.success()

    # --- auxiliares de planificación --------------------------------------- #

    @staticmethod
    def _session_duration(grid: TimeGrid, cell: tuple[int, int] | None) -> int:
        if cell is not None:
            periodo = grid.period(cell[1])
            if periodo is not None:
                return periodo.duration
        return dominant_teaching_duration(grid)

    @staticmethod
    def _lesson_cells(tt: Timetable | None, lesson: int) -> set[tuple[int, int]]:
        if tt is None:
            return set()
        return {a.slot for a in tt.assignments if a.lesson_number == lesson and a.line == 0}

    @staticmethod
    def _hard_blocks(project: UntisProject, le: Lesson) -> set[tuple[int, int]]:
        vetadas: set[tuple[int, int]] = set()
        grid = project.grid_by_id.get(le.time_grid)
        if grid is None:
            return vetadas
        entidades = [
            *((EntityKind.TEACHER, t) for t in le.teachers),
            *((EntityKind.CLASS, c) for c in le.classes),
            *((EntityKind.SUBJECT, s) for s in le.subjects),
        ]
        for kind, ident in entidades:
            for r in project.requests_for(kind, ident):
                if r.is_block:
                    for dia, per in grid.slots():
                        if r.covers(dia, per):
                            vetadas.add((dia, per))
        return vetadas

    @staticmethod
    def _occupancy(
        project: UntisProject,
        tt: Timetable | None,
        excluir: tuple[int, tuple[int, int] | None],
    ) -> dict[tuple[str, str, int], list[tuple[int, int, int]]]:
        """`(tipo, id, día) -> [(inicio, fin, lección)]` de las lecciones lectivas."""
        ocupacion: defaultdict[tuple[str, str, int], list[tuple[int, int, int]]] = defaultdict(list)
        if tt is None:
            return ocupacion
        lecciones = project.lesson_by_number
        grids = project.grid_by_id
        leccion_ex, celda_ex = excluir
        vistas: set[tuple[int, int, int]] = set()
        for a in tt.assignments:
            if a.lesson_number == leccion_ex and a.slot == celda_ex:
                continue
            le = lecciones.get(a.lesson_number)
            if le is None or _is_duty(le):
                continue
            grid = grids.get(le.time_grid)
            periodo = grid.period(a.period) if grid is not None else None
            if periodo is None:
                continue
            clave = (a.lesson_number, a.day, a.period)
            if clave not in vistas:
                vistas.add(clave)
                for t in le.teachers:
                    ocupacion[("teacher", t, a.day)].append(
                        (periodo.start, periodo.end, a.lesson_number)
                    )
                for c in le.classes:
                    ocupacion[("class", c, a.day)].append(
                        (periodo.start, periodo.end, a.lesson_number)
                    )
            if a.room is not None:
                ocupacion[("room", a.room, a.day)].append(
                    (periodo.start, periodo.end, a.lesson_number)
                )
        return ocupacion

    @staticmethod
    def _clash_reason(
        ocupacion: dict[tuple[str, str, int], list[tuple[int, int, int]]],
        le: Lesson,
        dia: int,
        inicio: int,
        fin: int,
    ) -> str:
        if _is_duty(le):
            return ""
        comprobar = [
            *(("teacher", t, "profesor") for t in le.teachers),
            *(("class", c, "clase") for c in le.classes),
            *(("room", line.room, "aula") for line in le.lines if line.room is not None),
        ]
        for tipo, ident, nombre in comprobar:
            for ini, fn, otra in ocupacion.get((tipo, ident, dia), ()):
                if otra != le.number and ini < fin and inicio < fn:
                    return f"{nombre} {ident} ocupado (lección {otra})"
        return ""

    @staticmethod
    def _moved(
        project: UntisProject,
        tt: Timetable,
        lesson: int,
        source: tuple[int, int] | None,
        target: tuple[int, int],
    ) -> Timetable | None:
        le = project.lesson_by_number.get(lesson)
        if le is None:
            return None
        dia, per = target
        if source is None:
            nuevas = tuple(
                Assignment(lesson, i, dia, per, room=line.room, manual=True)
                for i, line in enumerate(le.lines)
            )
            return dataclasses.replace(tt, assignments=(*tt.assignments, *nuevas))
        encontradas = [a for a in tt.assignments if a.lesson_number == lesson and a.slot == source]
        if not encontradas:
            return None
        movidas = tuple(
            dataclasses.replace(a, day=dia, period=per, manual=True) for a in encontradas
        )
        resto = tuple(
            a for a in tt.assignments if not (a.lesson_number == lesson and a.slot == source)
        )
        return dataclasses.replace(tt, assignments=(*resto, *movidas))


__all__ = ["PROJECT_SUFFIX", "UntisService"]
