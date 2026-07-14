"""Adaptador Untis -> Modelo Canónico.

Un colegio real no es el caso de juguete. Las claves de este export:

**Clases compartidas (acoples / Kopplungen).** En Untis, los alumnos de uno o
varios cursos pueden **repartirse en varios grupos paralelos** durante una
materia: N profesores dan la misma materia **a la vez**, cada uno con su aula,
y los estudiantes se distribuyen entre ellos. Dos ejemplos reales:

- *Alemán Klasse 4:* los cursos K4A..K4D se reparten en 5 grupos paralelos
  (5 profesores, 5 aulas) durante alemán.
- *Español IB:* 3 profesores para ``12-GIB 2/3/4/DSDA``; los alumnos de esos
  cursos se distribuyen en 3 sub-grupos.

Untis marca el acople con un **grupo de estudiantes** (``SG_...``): las líneas
que lo comparten corren a la misma hora. Una línea combinada (un profesor,
varios cursos) une transitivamente los cursos del acople. Modelamos cada acople
como **una sola tarea** que ocupa: todos sus profesores (a la vez), todos sus
cursos, y **tantas aulas como líneas paralelas** (una por profesor).

**Reloj real, no números de período.** Las 8 jornadas usan horas distintas para
el mismo número de período (el período 5 de Kinder coincide con el 6 de
Bachillerato). La rejilla es de minutos reales; cada clase dura lo que dura su
período (45 min domina; hay de 10/25/30/60).

**Obligaciones no lectivas.** Reuniones, extracurriculares, preparación,
almuerzos: docente sin curso ni aula. El propio horario de Untis las solapa con
clases, así que ni él las trata como exclusivas. Se excluyen por defecto.
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
class _Line:
    """Una lección individual: una línea de un acople (un profesor, su aula)."""

    lesson_id: str
    subject: str
    teacher: str | None
    courses: tuple[str, ...]
    studentgroup: str | None
    periods: int
    timegrid: str
    times: tuple[tuple[int, int, str | None], ...]  # (día, período, aula)


@dataclass(frozen=True, slots=True)
class Coupling:
    """Un acople: líneas que corren simultáneamente (misma clase compartida).

    Es la unidad real de planificación. Puede tener un solo profesor y un solo
    curso (clase normal) o varios de ambos (clase compartida / IB).
    """

    key: str
    subject: str
    teachers: tuple[str, ...]
    courses: tuple[str, ...]
    periods: int
    timegrid: str
    rooms_needed: int
    placements: tuple[tuple[int, int, tuple[str, ...]], ...]
    """Sesiones que Untis ubicó: (día, período, aulas usadas)."""

    @property
    def is_teaching(self) -> bool:
        return bool(self.courses)


@dataclass(frozen=True, slots=True)
class UntisTranslation:
    """Problema canónico + los mapeos para volver al mundo de Untis."""

    export: UntisExport
    problem: SchedulingProblem
    couplings: tuple[Coupling, ...]
    task_coupling: dict[int, str]
    task_session: dict[int, int]
    rid_of: dict[str, int]
    resource_name: dict[int, str]
    skipped: tuple[str, ...] = field(default_factory=tuple)
    pseudo_classes: tuple[str, ...] = field(default_factory=tuple)

    def slot_of(self, day: int, minute: int) -> int:
        largo = self.export.day_end - self.export.day_start
        return (day - 1) * largo + (minute - self.export.day_start)

    def decode(self, slot: int) -> tuple[int, int]:
        largo = self.export.day_end - self.export.day_start
        day, offset = divmod(slot, largo)
        return day + 1, self.export.day_start + offset

    def hhmm(self, slot: int) -> str:
        _, minuto = self.decode(slot)
        return f"{minuto // 60:02d}:{minuto % 60:02d}"


class _DSU:
    """Union-find para agrupar líneas en acoples."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self._parent[self.find(a)] = self.find(b)


@dataclass(frozen=True, slots=True)
class UntisToCanonicalAdapter:
    """Traduce un export de Untis al Modelo Canónico."""

    include_duties: bool = False
    """Incluir obligaciones no lectivas (docente sin curso) como exclusivas.
    Por defecto no: el propio horario de Untis las solapa con clases."""

    def translate(self, export: UntisExport) -> UntisTranslation:
        lines = self._lines(export)
        couplings = self._couple(lines)
        if not self.include_duties:
            couplings = tuple(c for c in couplings if c.is_teaching)

        declared = {c.id for c in export.classes}
        pseudo = self._pseudo_classes(couplings, declared)
        room_pools = self._room_pools(couplings)

        resources, rid_of, resource_name = self._build_resources(
            export, couplings, declared, room_pools
        )

        grid = TimeGrid.from_segment_lengths([export.day_end - export.day_start] * export.days)
        inicios = self._starts_by_grid_and_duration(export)

        tasks: list[Task] = []
        task_coupling: dict[int, str] = {}
        task_session: dict[int, int] = {}
        next_tid = 0
        for coupling in couplings:
            base = [ResourceRequirement(teacher_tag(t)) for t in coupling.teachers]
            base += [ResourceRequirement(group_tag(c)) for c in coupling.courses if c in declared]
            duracion = self._coupling_duration(export, coupling)
            permitidos = inicios.get((coupling.timegrid, duracion), ())
            if not base or not permitidos:
                continue
            slots = frozenset(
                TimeSlotIndex(self._slot(export, day, minuto)) for day, minuto in permitidos
            )
            nombre = f"{coupling.subject or '?'} · {'/'.join(coupling.courses)}"
            for index in range(coupling.periods):
                requirements = list(base)
                aulas = self._rooms_at(coupling, index)
                if aulas and room_pools.get(coupling.subject):
                    requirements.append(
                        ResourceRequirement(room_pool_tag(coupling.subject), quantity=len(aulas))
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
                task_coupling[next_tid] = coupling.key
                task_session[next_tid] = index
                next_tid += 1

        problem = SchedulingProblem(grid=grid, resources=tuple(resources), tasks=tuple(tasks))
        return UntisTranslation(
            export=export,
            problem=problem,
            couplings=couplings,
            task_coupling=task_coupling,
            task_session=task_session,
            rid_of=rid_of,
            resource_name=resource_name,
            skipped=tuple(ls.id for ls in export.lessons if not self._usable(ls)),
            pseudo_classes=pseudo,
        )

    # --- construcción de líneas y acoples ---

    @staticmethod
    def _usable(lesson: UntisLesson) -> bool:
        return lesson.periods > 0 and bool(lesson.teacher_id or lesson.class_ids)

    def _lines(self, export: UntisExport) -> list[_Line]:
        lines: list[_Line] = []
        for ls in export.lessons:
            if not self._usable(ls):
                continue
            times = tuple((t.day, t.period, t.room_id) for t in ls.times)
            lines.append(
                _Line(
                    lesson_id=ls.id,
                    subject=ls.subject_id or "",
                    teacher=ls.teacher_id,
                    courses=ls.class_ids,
                    studentgroup=ls.studentgroup_id,
                    periods=ls.periods,
                    timegrid=ls.timegrid,
                    times=times,
                )
            )
        return lines

    def _couple(self, lines: list[_Line]) -> tuple[Coupling, ...]:
        """Une líneas simultáneas: mismo grupo de estudiantes, o curso+materia
        compartidos (línea combinada). Todo dentro de la misma periodicidad."""
        dsu = _DSU(len(lines))
        by_sg: dict[tuple[str, int], list[int]] = defaultdict(list)
        by_course: dict[tuple[str, str, int], list[int]] = defaultdict(list)
        for i, line in enumerate(lines):
            if line.studentgroup:
                by_sg[(line.studentgroup, line.periods)].append(i)
            for course in line.courses:
                by_course[(course, line.subject, line.periods)].append(i)
        for grupo in by_sg.values():
            for j in grupo[1:]:
                dsu.union(grupo[0], j)
        for grupo in by_course.values():
            for j in grupo[1:]:
                dsu.union(grupo[0], j)

        componentes: dict[int, list[_Line]] = defaultdict(list)
        for i, line in enumerate(lines):
            componentes[dsu.find(i)].append(line)

        return tuple(self._make_coupling(group) for group in componentes.values())

    @staticmethod
    def _make_coupling(lines: list[_Line]) -> Coupling:
        teachers = tuple(dict.fromkeys(ln.teacher for ln in lines if ln.teacher))
        courses = tuple(dict.fromkeys(c for ln in lines for c in ln.courses))
        periods = max(ln.periods for ln in lines)
        subject = next((ln.subject for ln in lines if ln.subject), "")
        timegrid = next((ln.timegrid for ln in lines if ln.timegrid), "")

        # sesiones reales: por (día, período) -> aulas usadas
        por_slot: dict[tuple[int, int], set[str]] = defaultdict(set)
        for ln in lines:
            for day, period, room in ln.times:
                if room:
                    por_slot[(day, period)].add(room)
                else:
                    por_slot.setdefault((day, period), set())
        placements = tuple(
            (day, period, tuple(sorted(rooms))) for (day, period), rooms in sorted(por_slot.items())
        )
        rooms_needed = max((len(r) for _, _, r in placements), default=0)
        key = "COUP|" + ",".join(sorted(ln.lesson_id for ln in lines))
        return Coupling(
            key=key,
            subject=subject,
            teachers=teachers,
            courses=courses,
            periods=periods,
            timegrid=timegrid,
            rooms_needed=rooms_needed,
            placements=placements,
        )

    @staticmethod
    def _rooms_at(coupling: Coupling, index: int) -> tuple[str, ...]:
        if index < len(coupling.placements):
            return coupling.placements[index][2]
        # sesión que Untis no ubicó: se asume la necesidad típica del acople
        return tuple(f"?{i}" for i in range(coupling.rooms_needed))

    # --- recursos ---

    def _build_resources(
        self,
        export: UntisExport,
        couplings: tuple[Coupling, ...],
        declared: set[str],
        room_pools: dict[str, set[str]],
    ) -> tuple[list[Resource], dict[str, int], dict[int, str]]:
        nombres_docente = {t.id: t.name for t in export.teachers}
        nombres_curso = {c.id: c.name for c in export.classes}
        nombres_aula = {r.id: r.name for r in export.rooms}

        ids_docente = list(nombres_docente)
        ids_curso = list(nombres_curso)
        ids_aula = list(nombres_aula)
        for coupling in couplings:
            for t in coupling.teachers:
                if t not in nombres_docente:
                    nombres_docente[t] = t
                    ids_docente.append(t)
            for _, _, rooms in coupling.placements:
                for room in rooms:
                    if room not in nombres_aula:
                        nombres_aula[room] = room
                        ids_aula.append(room)

        resources: list[Resource] = []
        rid_of: dict[str, int] = {}
        resource_name: dict[int, str] = {}
        next_rid = 0

        def add(uid: str, name: str, tags: set[str]) -> None:
            nonlocal next_rid
            resources.append(Resource(ResourceId(next_rid), name, frozenset(tags)))
            resource_name[next_rid] = name
            rid_of[uid] = next_rid
            next_rid += 1

        for uid in ids_docente:
            add(uid, nombres_docente[uid], {TEACHER, teacher_tag(uid)})
        for uid in ids_curso:
            add(uid, nombres_curso[uid], {GROUP, group_tag(uid)})
        for uid in ids_aula:
            tags = {ROOM, f"room#{uid}"}
            tags.update(room_pool_tag(s) for s, pool in room_pools.items() if uid in pool)
            add(uid, nombres_aula[uid], tags)

        return resources, rid_of, resource_name

    @staticmethod
    def _pseudo_classes(couplings: tuple[Coupling, ...], declared: set[str]) -> tuple[str, ...]:
        pseudo: list[str] = []
        for coupling in couplings:
            for c in coupling.courses:
                if c not in declared and c not in pseudo:
                    pseudo.append(c)
        return tuple(pseudo)

    @staticmethod
    def _room_pools(couplings: tuple[Coupling, ...]) -> dict[str, set[str]]:
        pools: dict[str, set[str]] = defaultdict(set)
        for coupling in couplings:
            for _, _, rooms in coupling.placements:
                pools[coupling.subject].update(rooms)
        return pools

    # --- reloj real ---

    @staticmethod
    def _slot(export: UntisExport, day: int, minute: int) -> int:
        largo = export.day_end - export.day_start
        return (day - 1) * largo + (minute - export.day_start)

    @staticmethod
    def _starts_by_grid_and_duration(
        export: UntisExport,
    ) -> dict[tuple[str, int], tuple[tuple[int, int], ...]]:
        index: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
        for p in export.periods:
            index[(p.timegrid, p.duration)].append((p.day, p.start_min))
        return {k: tuple(sorted(v)) for k, v in index.items()}

    @staticmethod
    def _coupling_duration(export: UntisExport, coupling: Coupling) -> int:
        for day, period, _ in coupling.placements:
            p = export.period_at(coupling.timegrid, day, period)
            if p is not None:
                return p.duration
        return 45


def untis_reference_solution(translation: UntisTranslation) -> tuple[Solution, int]:
    """El horario que **Untis** produjo, traducido al Modelo Canónico."""
    rid_of = translation.rid_of
    export = translation.export
    coupling_by_key = {c.key: c for c in translation.couplings}

    assignments: list[Assignment] = []
    sin_ubicar = 0
    for tid, key in sorted(translation.task_coupling.items()):
        coupling = coupling_by_key[key]
        index = translation.task_session[tid]
        if index >= len(coupling.placements):
            sin_ubicar += 1
            continue
        day, period, rooms = coupling.placements[index]
        p = export.period_at(coupling.timegrid, day, period)
        if p is None:
            sin_ubicar += 1
            continue
        recursos = [rid_of[t] for t in coupling.teachers if t in rid_of]
        recursos += [rid_of[c] for c in coupling.courses if c in rid_of]
        recursos += [rid_of[r] for r in rooms if r in rid_of]
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
