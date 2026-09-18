"""`UntisProject` -> `SchedulingProblem` canónico, sin inferir acoples.

Es el único punto que traduce el dominio Untis al motor (ADR-034). Mantiene el
enfoque validado en ADR-016/017 —reloj de minutos, un `Task` por sesión que
ocupa a la vez todos los profesores, clases y aulas del acople— pero la unidad
de acople ya no se deduce con union-find: **el nº de lección manda**.

Convenciones del modelo canónico que se conservan (las usan plugins y
métricas del motor congelado):

- Etiquetas `teacher`, `group`, `room` para clasificar y `teacher#<id>`,
  `group#<id>`, `room#<id>` para fijar un recurso concreto.
- `roompool#<materia>`: aulas elegibles para la materia (optimización de aulas).
- `teacherpool#<materia>`: profesores elegibles cuando una línea no fija
  profesor (optimización de profesores).
- Nombre de tarea `"<materia> · <clases> #<sesión>"`: `SubjectSpreadPlugin`
  extrae la materia partiendo por `" · "`.

Decisiones que reflejan cómo trabaja Untis (medidas sobre el export real):

- **Duración por sesión.** Una sesión ocupa un período de su rejilla; el reloj
  de ese período fija su duración en minutos. Una sesión colocada por Untis
  conserva la duración de su período; una sesión nueva toma la duración
  dominante de su rejilla. Su dominio son los inicios de los períodos de esa
  rejilla con esa misma duración (los recreos y registros cortos quedan fuera
  de las lecciones de 45 min de forma natural).
- **Obligaciones no lectivas fuera.** Una lección sin clases ni grupo de
  alumnos (reunión, preparación, vigilancia) no es exclusiva: el propio horario
  publicado por Untis la solapa con clases 34 veces. Se excluyen por defecto
  (`include_duties=False`) y quedan listadas en `Translation.duties`.
- **Grupos de alumnos.** No son recurso propio: la exclusividad de la clase
  ya los cubre (0 solapes de clase entre lecciones distintas en el export).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
    TimeSlotIndex,
)
from scheduling_platform.untis_model import EntityKind, Lesson, TimeRequest, Timetable, UntisProject
from scheduling_platform.untis_model.sessions import reference_cells, session_durations

from .clock import Clock

TEACHER = "teacher"
GROUP = "group"
ROOM = "room"


def teacher_tag(uid: str) -> str:
    return f"teacher#{uid}"


def group_tag(uid: str) -> str:
    return f"group#{uid}"


def room_tag(uid: str) -> str:
    return f"room#{uid}"


def room_pool_tag(subject: str) -> str:
    return f"roompool#{subject}"


def teacher_pool_tag(subject: str) -> str:
    return f"teacherpool#{subject}"


class ResourceKind(StrEnum):
    """Tipo de recurso canónico, para volver del id al vocabulario Untis."""

    TEACHER = "teacher"
    CLASS = "class"
    ROOM = "room"


@dataclass(frozen=True, slots=True, order=True)
class SessionRef:
    """Sesión `session` (0-based) de la lección `lesson`: un `Task` canónico."""

    lesson: int
    session: int


@dataclass(frozen=True, slots=True)
class Translation:
    """Problema canónico y todo lo necesario para volver a Untis."""

    project: UntisProject
    problem: SchedulingProblem
    clock: Clock
    task_of: dict[SessionRef, int]
    session_of: dict[int, SessionRef]
    rid_of: dict[tuple[ResourceKind, str], int]
    entity_of: dict[int, tuple[ResourceKind, str]]
    durations: dict[SessionRef, int]
    """Duración en minutos de cada sesión traducida."""
    duties: tuple[int, ...] = field(default_factory=tuple)
    """Lecciones no lectivas excluidas (no son exclusivas, como en Untis)."""
    untranslatable: tuple[int, ...] = field(default_factory=tuple)
    """Lecciones sin recursos o sin períodos válidos en su rejilla."""

    def tasks_of_lesson(self, lesson: int) -> tuple[int, ...]:
        """Tareas canónicas de una lección, en orden de sesión."""
        return tuple(
            tid
            for ref, tid in sorted(self.task_of.items(), key=lambda kv: kv[0].session)
            if ref.lesson == lesson
        )


# --------------------------------------------------------------------------- #
# Auxiliares puros
# --------------------------------------------------------------------------- #


def is_duty(lesson: Lesson) -> bool:
    """`True` si la lección no tiene alumnos (obligación no lectiva)."""
    return not any(line.classes or line.student_group for line in lesson.lines)


def reference_line_rooms(
    timetable: Timetable | None,
) -> dict[tuple[int, int, int], dict[int, str]]:
    """Aula de cada línea en cada celda: `(lección, día, período) -> {línea: aula}`.

    El aula no va siempre en la línea 0: en el export real hay acoples con el
    aula en la línea 1. Conservar la línea evita barajar aulas entre profesores.
    """
    por_celda: defaultdict[tuple[int, int, int], dict[int, str]] = defaultdict(dict)
    if timetable is not None:
        for a in timetable.assignments:
            if a.room is not None:
                por_celda[(a.lesson_number, a.day, a.period)][a.line] = a.room
    return dict(por_celda)


def reference_rooms(timetable: Timetable | None) -> dict[tuple[int, int, int], tuple[str, ...]]:
    """Aulas distintas usadas por cada lección en cada celda, en orden de línea."""
    return {
        celda: tuple(dict.fromkeys(aula for _, aula in sorted(lineas.items())))
        for celda, lineas in reference_line_rooms(timetable).items()
    }


@dataclass(frozen=True, slots=True)
class _CellFilter:
    """`(día, período) in filtro` es `True` si algún deseo -3 veta esa celda."""

    rules: tuple[TimeRequest, ...]

    def __contains__(self, cell: object) -> bool:
        if not isinstance(cell, tuple) or len(cell) != 2:
            return False
        dia, periodo = cell
        return any(r.covers(dia, periodo) for r in self.rules)


# --------------------------------------------------------------------------- #
# Traductor
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class UntisTranslator:
    """Traduce un `UntisProject` al modelo canónico."""

    include_duties: bool = False
    optimize_teachers: bool = False
    """Optimización de profesores (casilla del diálogo de Optimización).

    Como en Untis, es opt-in: sin ella, una línea sin profesor simplemente no
    ocupa a nadie. Con ella, pide un profesor del pool de su materia.
    """
    reference: str | None = None
    """Id del horario de referencia (duraciones y aulas); `None` = el primero."""

    def translate(self, project: UntisProject) -> Translation:
        clock = Clock.of_project(project)
        referencia = self._reference(project)
        celdas = reference_cells(referencia)
        aulas_ref = reference_rooms(referencia)
        grids = project.grid_by_id

        activas = [le for le in project.active_lessons if le.periods_per_week > 0]
        deberes = tuple(le.number for le in activas if is_duty(le))
        lecciones = [le for le in activas if self.include_duties or not is_duty(le)]

        room_pools = self._room_pools(project, lecciones, aulas_ref)
        teacher_pools = self._teacher_pools(project)
        resources, rid_of, entity_of = self._resources(project, room_pools, teacher_pools)

        celdas_por = self._cells_by_grid_and_duration(project, clock)
        bloqueos = self._hard_blocks(project)

        tasks: list[Task] = []
        task_of: dict[SessionRef, int] = {}
        session_of: dict[int, SessionRef] = {}
        durations: dict[SessionRef, int] = {}
        sin_traducir: list[int] = []

        for le in lecciones:
            base = self._base_requirements(
                le, rid_of, teacher_pools if self.optimize_teachers else {}
            )
            if not base:
                sin_traducir.append(le.number)
                continue
            grid = grids.get(le.time_grid)
            colocadas = celdas.get(le.number, [])
            nombre = f"{le.subjects[0] if le.subjects else '?'} · {'/'.join(le.classes)}"
            duraciones = session_durations(le, grid, colocadas)
            vetadas = self._blocked_cells(le, bloqueos)
            anadidas = 0
            for sesion, duracion in enumerate(duraciones):
                candidatas = celdas_por.get((le.time_grid, duracion), ())
                if le.fixed and sesion < len(colocadas):
                    # Lección fijada: cada sesión queda en su celda de referencia.
                    candidatas = tuple(c for c in candidatas if c[:2] == colocadas[sesion])
                permitidos = frozenset(
                    TimeSlotIndex(slot)
                    for dia, per, slot in candidatas
                    if (dia, per) not in vetadas
                )
                if not permitidos:
                    continue
                requisitos = list(base)
                aulas = self._rooms_for(le, sesion, colocadas, aulas_ref)
                if aulas:
                    tag = room_pool_tag(le.subjects[0])
                    requisitos.append(ResourceRequirement(tag, quantity=len(aulas)))
                tid = len(tasks)
                ref = SessionRef(le.number, sesion)
                tasks.append(
                    Task(
                        TaskId(tid),
                        f"{nombre} #{sesion + 1}",
                        duracion,
                        tuple(requisitos),
                        allowed_starts=permitidos,
                    )
                )
                task_of[ref] = tid
                session_of[tid] = ref
                durations[ref] = duracion
                anadidas += 1
            if anadidas == 0:
                sin_traducir.append(le.number)

        grid_canonica = TimeGrid.from_segment_lengths([clock.day_length] * len(clock.days))
        problem = SchedulingProblem(
            grid=grid_canonica, resources=tuple(resources), tasks=tuple(tasks)
        )
        return Translation(
            project=project,
            problem=problem,
            clock=clock,
            task_of=task_of,
            session_of=session_of,
            rid_of=rid_of,
            entity_of=entity_of,
            durations=durations,
            duties=deberes,
            untranslatable=tuple(sin_traducir),
        )

    # --- referencia --------------------------------------------------------- #

    def _reference(self, project: UntisProject) -> Timetable | None:
        if self.reference is not None:
            return project.timetable_by_id(self.reference)
        return project.timetables[0] if project.timetables else None

    # --- recursos ------------------------------------------------------------ #

    @staticmethod
    def _room_pools(
        project: UntisProject,
        lecciones: list[Lesson],
        aulas_ref: dict[tuple[int, int, int], tuple[str, ...]],
    ) -> dict[str, set[str]]:
        """Aulas elegibles por materia: las usadas, las fijadas y sus cadenas."""
        aulas = project.room_by_id
        pools: defaultdict[str, set[str]] = defaultdict(set)
        materia_de = {le.number: le.subjects[0] for le in lecciones if le.subjects}
        for (numero, _, _), usadas in aulas_ref.items():
            if numero in materia_de:
                pools[materia_de[numero]].update(r for r in usadas if r in aulas)
        for le in lecciones:
            if not le.subjects:
                continue
            for line in le.lines:
                for candidata in (line.room, line.alternative_room):
                    if candidata is not None and candidata in aulas:
                        pools[le.subjects[0]].add(candidata)
        # La cadena de aulas alternativas amplía el pool (optimización de aulas).
        for materia, pool in pools.items():
            pendientes = list(pool)
            while pendientes:
                siguiente = aulas[pendientes.pop()].alternative_room
                if siguiente is not None and siguiente in aulas and siguiente not in pool:
                    pool.add(siguiente)
                    pendientes.append(siguiente)
            pools[materia] = pool
        return dict(pools)

    @staticmethod
    def _teacher_pools(project: UntisProject) -> dict[str, set[str]]:
        """Profesores que imparten cada materia en algún sitio del proyecto."""
        pools: defaultdict[str, set[str]] = defaultdict(set)
        for le in project.lessons:
            for line in le.lines:
                if line.teacher is not None:
                    pools[line.subject].add(line.teacher)
        return dict(pools)

    @staticmethod
    def _resources(
        project: UntisProject,
        room_pools: dict[str, set[str]],
        teacher_pools: dict[str, set[str]],
    ) -> tuple[
        list[Resource],
        dict[tuple[ResourceKind, str], int],
        dict[int, tuple[ResourceKind, str]],
    ]:
        pools_de_aula: defaultdict[str, set[str]] = defaultdict(set)
        for materia, pool in room_pools.items():
            for aula in pool:
                pools_de_aula[aula].add(room_pool_tag(materia))
        pools_de_profe: defaultdict[str, set[str]] = defaultdict(set)
        for materia, pool in teacher_pools.items():
            for profe in pool:
                pools_de_profe[profe].add(teacher_pool_tag(materia))

        resources: list[Resource] = []
        rid_of: dict[tuple[ResourceKind, str], int] = {}
        entity_of: dict[int, tuple[ResourceKind, str]] = {}

        def add(kind: ResourceKind, uid: str, name: str, tags: set[str], seats: int) -> None:
            rid = len(resources)
            atributos = (("seats", seats),) if seats > 0 else ()
            resources.append(
                Resource(ResourceId(rid), name or uid, frozenset(tags), attributes=atributos)
            )
            rid_of[(kind, uid)] = rid
            entity_of[rid] = (kind, uid)

        for t in project.teachers:
            add(
                ResourceKind.TEACHER,
                t.id,
                t.display_name,
                {TEACHER, teacher_tag(t.id), *pools_de_profe.get(t.id, set())},
                0,
            )
        for c in project.classes:
            add(ResourceKind.CLASS, c.id, c.display_name, {GROUP, group_tag(c.id)}, 0)
        for r in project.rooms:
            add(
                ResourceKind.ROOM,
                r.id,
                r.display_name,
                {ROOM, room_tag(r.id), *pools_de_aula.get(r.id, set())},
                r.capacity or 0,
            )
        return resources, rid_of, entity_of

    @staticmethod
    def _base_requirements(
        le: Lesson,
        rid_of: dict[tuple[ResourceKind, str], int],
        teacher_pools: dict[str, set[str]],
    ) -> list[ResourceRequirement]:
        """Profesores y clases del acople, ocupados a la vez."""
        req: list[ResourceRequirement] = [
            ResourceRequirement(teacher_tag(t))
            for t in le.teachers
            if (ResourceKind.TEACHER, t) in rid_of
        ]
        # Optimización de profesores: cada línea sin profesor pide uno del pool
        # de su materia. El `ValidationEngine` cuenta *todos* los recursos
        # asignados con la etiqueta del pool, y los profesores fijos de esa
        # materia también la llevan: la cantidad debe incluirlos.
        abiertas: Counter[str] = Counter(
            line.subject
            for line in le.lines
            if line.teacher is None and teacher_pools.get(line.subject)
        )
        for materia, huecos in sorted(abiertas.items()):
            fijos = sum(1 for t in le.teachers if t in teacher_pools[materia])
            req.append(ResourceRequirement(teacher_pool_tag(materia), quantity=fijos + huecos))
        req += [
            ResourceRequirement(group_tag(c))
            for c in le.classes
            if (ResourceKind.CLASS, c) in rid_of
        ]
        return req

    # --- tiempo --------------------------------------------------------------- #

    @staticmethod
    def _cells_by_grid_and_duration(
        project: UntisProject, clock: Clock
    ) -> dict[tuple[str, int], tuple[tuple[int, int, int], ...]]:
        """Celdas lectivas `(día, período, slot canónico)` por rejilla y duración."""
        indice: defaultdict[tuple[str, int], list[tuple[int, int, int]]] = defaultdict(list)
        for g in project.time_grids:
            for p in g.teaching_periods:
                for d in sorted(g.days):
                    indice[(g.id, p.duration)].append((d, p.number, clock.slot(d, p.start)))
        return {k: tuple(v) for k, v in indice.items()}

    @staticmethod
    def _hard_blocks(project: UntisProject) -> dict[tuple[EntityKind, str], list[TimeRequest]]:
        """Deseos -3 (imposible) por entidad: recortan el dominio, son duros."""
        indice: defaultdict[tuple[EntityKind, str], list[TimeRequest]] = defaultdict(list)
        for r in project.time_requests:
            if r.is_block:
                indice[(r.entity_kind, r.entity_id)].append(r)
        return dict(indice)

    @staticmethod
    def _blocked_cells(
        le: Lesson, bloqueos: dict[tuple[EntityKind, str], list[TimeRequest]]
    ) -> _CellFilter:
        """Filtro de celdas vetadas por los deseos -3 de cualquier entidad del acople."""
        reglas: list[TimeRequest] = []
        for t in le.teachers:
            reglas += bloqueos.get((EntityKind.TEACHER, t), [])
        for c in le.classes:
            reglas += bloqueos.get((EntityKind.CLASS, c), [])
        for m in le.subjects:
            reglas += bloqueos.get((EntityKind.SUBJECT, m), [])
        for line in le.lines:
            if line.room is not None:
                reglas += bloqueos.get((EntityKind.ROOM, line.room), [])
        return _CellFilter(tuple(reglas))

    @staticmethod
    def _rooms_for(
        le: Lesson,
        sesion: int,
        colocadas: list[tuple[int, int]],
        aulas_ref: dict[tuple[int, int, int], tuple[str, ...]],
    ) -> tuple[str, ...]:
        """Aulas que necesita una sesión: las que usó Untis o las pedidas por línea."""
        if sesion < len(colocadas):
            dia, periodo = colocadas[sesion]
            usadas = aulas_ref.get((le.number, dia, periodo))
            if usadas:
                return usadas
        return tuple(dict.fromkeys(line.room for line in le.lines if line.room is not None))


def translate(project: UntisProject, *, include_duties: bool = False) -> Translation:
    """Atajo: traduce con el horario de referencia por defecto."""
    return UntisTranslator(include_duties=include_duties).translate(project)
