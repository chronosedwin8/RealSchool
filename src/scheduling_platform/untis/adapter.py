"""Adaptador Untis -> Modelo Canónico.

Un colegio real no es el caso de juguete: aquí aparecen la **co-docencia** (dos
profesores en la misma clase), las **clases acopladas** (una lección para varios
cursos a la vez) y las **obligaciones sin curso** (guardias, reuniones). El
Modelo Canónico ya soporta todo eso sin cambiar una línea: una tarea puede
requerir varios recursos con tags distintos.

Decisiones de interpretación (documentadas porque condicionan la comparación):

- **Co-docencia:** Untis modela dos profesores en la misma clase como *dos
  lecciones* con el mismo grupo de estudiantes, materia y curso. Tomadas por
  separado, el no-solape del curso las declararía en conflicto consigo mismas.
  Se **fusionan** en un único curso con varios docentes: es lo que ocurre en la
  realidad.
- **Aulas:** el export no dice qué aula *puede* usar cada materia, solo cuál usó.
  Se deriva un *pool* por materia (la unión de las aulas que esa materia ocupó en
  el horario real). Es data-driven y no fija el aula de cada clase concreta.
  El aula se pide **sesión a sesión**: Untis asigna aula a unas sesiones de un
  curso y a otras no, y forzarla en todas declararía inválido su propio horario.
- **Pseudo-cursos:** los ids de curso que las lecciones referencian pero que
  Untis **no declara** (``CL_12-GIB``, etc.) no son cursos reales: son grupos de
  opción del Bachillerato Internacional, donde los alumnos se reparten y varias
  clases corren en paralelo. Tratarlos como un curso unario haría el problema
  imposible (uno de ellos "necesitaría" 132 períodos en una semana de 75). Se
  registran, pero no imponen no-solape.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..core.assignment import Assignment
from ..core.ids import ResourceId, TaskId, TimeSlotIndex
from ..core.problem import SchedulingProblem
from ..core.requirement import ResourceRequirement
from ..core.resource import Resource
from ..core.solution import Solution
from ..core.task import Task
from ..core.time_grid import TimeGrid
from .parser import UntisExport, UntisLesson

TEACHER = "teacher"
GROUP = "group"
ROOM = "room"


def teacher_tag(uid: str) -> str:
    return f"teacher#{uid}"


def group_tag(uid: str) -> str:
    return f"group#{uid}"


def room_pool_tag(subject_id: str) -> str:
    return f"roompool#{subject_id}"


@dataclass(frozen=True, slots=True)
class Course:
    """Lecciones de Untis ya fusionadas: una clase semanal real."""

    key: str
    subject_id: str
    teacher_ids: tuple[str, ...]
    class_ids: tuple[str, ...]
    periods: int
    needs_room: bool
    timegrid: str
    times: tuple[tuple[int, int, str | None], ...]
    """Sesiones que Untis ubicó: (día, período, aula)."""


@dataclass(frozen=True, slots=True)
class UntisTranslation:
    """Problema canónico + los mapeos para volver al mundo de Untis."""

    export: UntisExport
    problem: SchedulingProblem
    courses: tuple[Course, ...]
    task_course: dict[int, str]
    task_session: dict[int, int]
    """Tarea -> índice de la sesión dentro de su curso (alinea con los tiempos de Untis)."""
    resource_name: dict[int, str]
    resource_kind: dict[int, str]
    rid_of: dict[str, int]
    """id de Untis (docente/curso/aula) -> id del recurso canónico."""
    skipped: tuple[str, ...] = field(default_factory=tuple)
    """Lecciones descartadas (sin ningún recurso que requerir)."""
    pseudo_classes: tuple[str, ...] = field(default_factory=tuple)
    """Cursos referenciados pero no declarados: grupos de opción, no cursos."""

    def slot_of(self, day: int, minute: int) -> int:
        """Minuto de reloj de un día -> slot canónico."""
        largo = self.export.day_end - self.export.day_start
        return (day - 1) * largo + (minute - self.export.day_start)

    def decode(self, slot: int) -> tuple[int, int]:
        """Slot canónico -> (día, minuto de reloj)."""
        largo = self.export.day_end - self.export.day_start
        day, offset = divmod(slot, largo)
        return day + 1, self.export.day_start + offset

    def hhmm(self, slot: int) -> str:
        _, minuto = self.decode(slot)
        return f"{minuto // 60:02d}:{minuto % 60:02d}"


@dataclass(frozen=True, slots=True)
class UntisToCanonicalAdapter:
    """Traduce un export de Untis al Modelo Canónico."""

    include_duties: bool = False
    """¿Incluir las obligaciones no lectivas (reuniones, extracurriculares,
    preparación, almuerzos) como tareas que ocupan al docente en exclusiva?

    Por defecto **no**. Un colegio real las tiene, pero no son clases: el propio
    horario de Untis solapa esas entradas con clases, de modo que ni siquiera él
    las trata como exclusivas. Incluirlas con no-solape estricto sobrerrestringe
    el problema y compara peras con manzanas.
    """

    def translate(self, export: UntisExport) -> UntisTranslation:
        courses = tuple(
            c for c in self._merge_lessons(export) if self.include_duties or self._is_teaching(c)
        )
        room_pools = self._room_pools(courses)

        # Cursos REALES: solo los que Untis declara. Los que aparecen únicamente
        # en las lecciones son grupos de opción (ver docstring), no cursos.
        declarados = {c.id for c in export.classes}
        pseudo: list[str] = []

        nombres_docente = {t.id: t.name for t in export.teachers}
        nombres_curso = {c.id: c.name for c in export.classes}
        nombres_aula = {r.id: r.name for r in export.rooms}

        ids_docente = list(nombres_docente)
        ids_curso = list(nombres_curso)
        ids_aula = list(nombres_aula)
        for course in courses:
            for tid in course.teacher_ids:
                if tid not in nombres_docente:
                    nombres_docente[tid] = tid
                    ids_docente.append(tid)
            for cid in course.class_ids:
                if cid not in declarados and cid not in pseudo:
                    pseudo.append(cid)
            for _, _, room in course.times:
                if room and room not in nombres_aula:
                    nombres_aula[room] = room
                    ids_aula.append(room)

        resources: list[Resource] = []
        resource_name: dict[int, str] = {}
        resource_kind: dict[int, str] = {}
        rid_of: dict[str, int] = {}
        next_rid = 0

        for uid in ids_docente:
            resources.append(
                Resource(
                    ResourceId(next_rid),
                    nombres_docente[uid],
                    frozenset({TEACHER, teacher_tag(uid)}),
                )
            )
            resource_name[next_rid] = nombres_docente[uid]
            resource_kind[next_rid] = TEACHER
            rid_of[uid] = next_rid
            next_rid += 1

        for uid in ids_curso:
            resources.append(
                Resource(
                    ResourceId(next_rid), nombres_curso[uid], frozenset({GROUP, group_tag(uid)})
                )
            )
            resource_name[next_rid] = nombres_curso[uid]
            resource_kind[next_rid] = GROUP
            rid_of[uid] = next_rid
            next_rid += 1

        for uid in ids_aula:
            tags = {ROOM, f"room#{uid}"}
            tags.update(room_pool_tag(sid) for sid, pool in room_pools.items() if uid in pool)
            resources.append(Resource(ResourceId(next_rid), nombres_aula[uid], frozenset(tags)))
            resource_name[next_rid] = nombres_aula[uid]
            resource_kind[next_rid] = ROOM
            rid_of[uid] = next_rid
            next_rid += 1

        # Rejilla de TIEMPO DE RELOJ, no de números de período: cada jornada usa
        # horas distintas para el mismo número (el período 5 de Kinder coincide
        # con el 6 de Bachillerato). Modelarlo por número declararía simultáneas
        # clases que no lo son, y no simultáneas las que sí.
        largo_dia = export.day_end - export.day_start
        grid = TimeGrid.from_segment_lengths([largo_dia] * export.days)
        inicios = self._starts_by_grid_and_duration(export)

        tasks: list[Task] = []
        task_course: dict[int, str] = {}
        task_session: dict[int, int] = {}
        next_tid = 0
        for course in courses:
            base = [ResourceRequirement(teacher_tag(t)) for t in course.teacher_ids]
            base += [ResourceRequirement(group_tag(c)) for c in course.class_ids if c in declarados]
            tiene_pool = bool(room_pools.get(course.subject_id))
            nombre = f"{course.subject_id or '?'} · {'/'.join(course.class_ids) or 'sin curso'}"

            for index in range(course.periods):
                requirements = list(base)
                if tiene_pool and self._session_needs_room(course, index):
                    requirements.append(ResourceRequirement(room_pool_tag(course.subject_id)))
                if not requirements:
                    continue

                duracion = self._session_duration(export, course, index)
                permitidos = inicios.get((course.timegrid, duracion), ())
                if not permitidos:
                    continue  # su jornada no ofrece ningún período de esa duración
                slots = frozenset(
                    TimeSlotIndex((day - 1) * largo_dia + (minuto - export.day_start))
                    for day, minuto in permitidos
                )
                tasks.append(
                    Task(
                        TaskId(next_tid),
                        f"{nombre} #{index + 1}",
                        duracion,
                        tuple(requirements),
                        allowed_starts=slots,
                    )
                )
                task_course[next_tid] = course.key
                task_session[next_tid] = index
                next_tid += 1

        problem = SchedulingProblem(grid=grid, resources=tuple(resources), tasks=tuple(tasks))
        return UntisTranslation(
            export=export,
            problem=problem,
            courses=courses,
            task_course=task_course,
            task_session=task_session,
            resource_name=resource_name,
            resource_kind=resource_kind,
            rid_of=rid_of,
            skipped=self._skipped(export),
            pseudo_classes=tuple(pseudo),
        )

    @staticmethod
    def _is_teaching(course: Course) -> bool:
        """¿Es una clase de verdad? Lo es si tiene alumnos a los que dar clase."""
        return bool(course.class_ids)

    @staticmethod
    def _starts_by_grid_and_duration(
        export: UntisExport,
    ) -> dict[tuple[str, int], tuple[tuple[int, int], ...]]:
        """(jornada, duración) -> (día, minuto de inicio) de los períodos que encajan.

        Una clase de 45 minutos de Primaria puede ir en cualquier período de 45
        minutos de Primaria, en cualquier día. Eso es lo que define su dominio
        temporal.
        """
        index: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
        for p in export.periods:
            index[(p.timegrid, p.duration)].append((p.day, p.start_min))
        return {k: tuple(sorted(v)) for k, v in index.items()}

    @staticmethod
    def _session_duration(export: UntisExport, course: Course, index: int) -> int:
        """Duración real (minutos) de una sesión, según el período que ocupa."""
        if index < len(course.times):
            day, period, _ = course.times[index]
            p = export.period_at(course.timegrid, day, period)
            if p is not None:
                return p.duration
        # Sesión que Untis no ubicó: se asume la duración dominante del curso.
        for i in range(len(course.times)):
            day, period, _ = course.times[i]
            p = export.period_at(course.timegrid, day, period)
            if p is not None:
                return p.duration
        return 45

    @staticmethod
    def _session_needs_room(course: Course, index: int) -> bool:
        """¿Untis le dio aula a *esta* sesión concreta?"""
        if index < len(course.times):
            return course.times[index][2] is not None
        return course.needs_room  # sesión que Untis no ubicó: se asume como el curso

    # --- interpretación ---

    @staticmethod
    def _merge_lessons(export: UntisExport) -> tuple[Course, ...]:
        """Fusiona las lecciones co-docentes en un solo curso.

        La co-docencia se identifica por el **grupo de estudiantes compartido**:
        son los mismos alumnos recibiendo la misma materia. Una lección sin grupo
        de estudiantes (guardia, extracurricular, reunión) no se fusiona con
        nada: dos profesores distintos con "Extracurricular" no están dando la
        misma clase, y fusionarlos los obligaría a coincidir en el tiempo.
        """
        grupos: dict[tuple[str, ...], list[UntisLesson]] = defaultdict(list)
        for lesson in export.lessons:
            if not UntisToCanonicalAdapter._usable(lesson):
                continue
            if lesson.studentgroup_id:
                clave = (
                    lesson.studentgroup_id,
                    lesson.subject_id or "",
                    *lesson.class_ids,
                    str(lesson.periods),
                )
            else:
                clave = ("__sola__", lesson.id)  # sin grupo: no se fusiona
            grupos[clave].append(lesson)

        courses: list[Course] = []
        for clave, lessons in grupos.items():
            primera = lessons[0]
            subject = primera.subject_id
            classes = primera.class_ids
            periods = primera.periods
            teachers = tuple(dict.fromkeys(ls.teacher_id for ls in lessons if ls.teacher_id))
            times: tuple[tuple[int, int, str | None], ...] = ()
            needs_room = False
            for ls in lessons:
                if any(t.room_id for t in ls.times):
                    needs_room = True
                if not times and ls.times:
                    times = tuple((t.day, t.period, t.room_id) for t in ls.times)
                elif ls.times and not any(r for _, _, r in times):
                    # preferimos la lección que sí trae aula asignada
                    candidato = tuple((t.day, t.period, t.room_id) for t in ls.times)
                    if any(r for _, _, r in candidato):
                        times = candidato
            key = "|".join(clave)
            courses.append(
                Course(
                    key=key,
                    subject_id=subject or "",
                    teacher_ids=teachers,
                    class_ids=classes,
                    periods=periods,
                    needs_room=needs_room,
                    timegrid=primera.timegrid,
                    times=times,
                )
            )
        return tuple(courses)

    @staticmethod
    def _usable(lesson: UntisLesson) -> bool:
        """Una lección sirve si consume algún recurso y ocupa tiempo."""
        return lesson.periods > 0 and bool(lesson.teacher_id or lesson.class_ids)

    @staticmethod
    def _skipped(export: UntisExport) -> tuple[str, ...]:
        return tuple(ls.id for ls in export.lessons if not UntisToCanonicalAdapter._usable(ls))

    @staticmethod
    def _room_pools(courses: tuple[Course, ...]) -> dict[str, set[str]]:
        """Aulas que cada materia usó en el horario real."""
        pools: dict[str, set[str]] = defaultdict(set)
        for course in courses:
            for _, _, room in course.times:
                if room:
                    pools[course.subject_id].add(room)
        return pools


def untis_reference_solution(translation: UntisTranslation) -> tuple[Solution, int]:
    """El horario que **Untis** produjo, traducido al Modelo Canónico.

    Es la línea base del Gap Analysis: permite calcular sus KPIs con la misma
    vara con la que medimos los nuestros. Devuelve la solución y cuántas
    sesiones dejó Untis sin ubicar.
    """
    rid_of = translation.rid_of
    export = translation.export
    course_by_key = {c.key: c for c in translation.courses}

    assignments: list[Assignment] = []
    sin_ubicar = 0
    for tid, key in sorted(translation.task_course.items()):
        course = course_by_key[key]
        index = translation.task_session[tid]
        if index >= len(course.times):
            sin_ubicar += 1  # Untis no llegó a ubicar esta sesión
            continue
        day, period, room = course.times[index]
        p = export.period_at(course.timegrid, day, period)
        if p is None:
            sin_ubicar += 1
            continue
        recursos = [rid_of[t] for t in course.teacher_ids if t in rid_of]
        recursos += [rid_of[c] for c in course.class_ids if c in rid_of]
        if room and room in rid_of:
            recursos.append(rid_of[room])
        if not recursos:
            sin_ubicar += 1
            continue
        assignments.append(
            Assignment(
                TaskId(tid),
                TimeSlotIndex(translation.slot_of(day, p.start_min)),
                tuple(ResourceId(r) for r in sorted(set(recursos))),
            )
        )

    return Solution(assignments=tuple(assignments), objective_value=0), sin_ubicar
