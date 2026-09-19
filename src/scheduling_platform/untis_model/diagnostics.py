"""Diagnóstico de datos de entrada (rama "Datos de entrada" del Diagnóstico).

Comprueba el proyecto antes de optimizar: referencias rotas, cargas imposibles,
deseos contradictorios. Untis muestra esto como errores y advertencias; aquí es
una lista de `DataIssue` que la UI agrupa por severidad y criterio.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from .common import REQUEST_MAX, REQUEST_MIN, EntityKind
from .lessons import LessonLine
from .project import UntisProject
from .requests import TimeRequest


class Severity(StrEnum):
    """Gravedad de un hallazgo del diagnóstico de datos."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class DataIssue:
    """Un hallazgo del diagnóstico, con el salto a la entidad que lo provoca."""

    severity: Severity
    code: str
    message: str
    entity_kind: EntityKind | None = None
    entity_id: str = ""
    lesson_number: int | None = None

    @property
    def is_error(self) -> bool:
        """`True` si el hallazgo impide optimizar."""
        return self.severity is Severity.ERROR


@dataclass(frozen=True, slots=True)
class _Ids:
    """Conjuntos de ids precalculados una sola vez por diagnóstico."""

    subjects: frozenset[str]
    teachers: frozenset[str]
    classes: frozenset[str]
    student_groups: frozenset[str]
    rooms: frozenset[str]

    @classmethod
    def of(cls, project: UntisProject) -> _Ids:
        return cls(
            subjects=frozenset(s.id for s in project.subjects),
            teachers=frozenset(t.id for t in project.teachers),
            classes=frozenset(c.id for c in project.classes),
            student_groups=frozenset(g.id for g in project.student_groups),
            rooms=frozenset(r.id for r in project.rooms),
        )


def _check_master_data(project: UntisProject) -> list[DataIssue]:
    """Rejillas, clases y profesores: referencias a entidades inexistentes."""
    issues: list[DataIssue] = []
    grids = project.grid_by_id
    aulas = project.room_by_id

    for g in project.time_grids:
        if not g.teaching_periods:
            issues.append(
                DataIssue(
                    Severity.ERROR,
                    "grid_sin_periodos",
                    f"La rejilla {g.display_name!r} no tiene períodos lectivos.",
                )
            )

    for c in project.classes:
        if c.time_grid and c.time_grid not in grids:
            issues.append(
                DataIssue(
                    Severity.ERROR,
                    "clase_rejilla_inexistente",
                    f"La clase {c.display_name!r} apunta a la rejilla "
                    f"{c.time_grid!r}, que no existe.",
                    EntityKind.CLASS,
                    c.id,
                )
            )
        if c.home_room and c.home_room not in aulas:
            issues.append(
                DataIssue(
                    Severity.WARNING,
                    "clase_aula_base_inexistente",
                    f"La clase {c.display_name!r} tiene como aula base "
                    f"{c.home_room!r}, que no existe.",
                    EntityKind.CLASS,
                    c.id,
                )
            )

    for t in project.teachers:
        if t.home_room and t.home_room not in aulas:
            issues.append(
                DataIssue(
                    Severity.WARNING,
                    "profesor_aula_base_inexistente",
                    f"El profesor {t.display_name!r} tiene como aula base "
                    f"{t.home_room!r}, que no existe.",
                    EntityKind.TEACHER,
                    t.id,
                )
            )

    return issues


def _check_room_chains(project: UntisProject) -> list[DataIssue]:
    """La cadena de aulas alternativas debe terminar y no repetirse."""
    issues: list[DataIssue] = []
    aulas = project.room_by_id

    for r in project.rooms:
        visto: set[str] = {r.id}
        actual = r.alternative_room
        while actual is not None:
            if actual not in aulas:
                issues.append(
                    DataIssue(
                        Severity.WARNING,
                        "aula_alternativa_inexistente",
                        f"El aula {r.display_name!r} encadena con {actual!r}, que no existe.",
                        EntityKind.ROOM,
                        r.id,
                    )
                )
                break
            if actual in visto:
                issues.append(
                    DataIssue(
                        Severity.ERROR,
                        "aula_cadena_ciclica",
                        f"La cadena de aulas alternativas desde {r.display_name!r} es cíclica.",
                        EntityKind.ROOM,
                        r.id,
                    )
                )
                break
            visto.add(actual)
            actual = aulas[actual].alternative_room

    return issues


def _check_lesson_line(
    ids: _Ids, lesson_number: int, index: int, line: LessonLine
) -> list[DataIssue]:
    """Referencias de una línea de acople."""
    issues: list[DataIssue] = []

    if line.subject not in ids.subjects:
        issues.append(
            DataIssue(
                Severity.ERROR,
                "linea_materia_inexistente",
                f"La lección {lesson_number}, línea {index}, usa la materia "
                f"{line.subject!r}, que no existe.",
                EntityKind.SUBJECT,
                line.subject,
                lesson_number,
            )
        )
    if line.teacher is not None and line.teacher not in ids.teachers:
        issues.append(
            DataIssue(
                Severity.ERROR,
                "linea_profesor_inexistente",
                f"La lección {lesson_number}, línea {index}, usa el profesor "
                f"{line.teacher!r}, que no existe.",
                EntityKind.TEACHER,
                line.teacher,
                lesson_number,
            )
        )
    for cid in line.classes:
        if cid not in ids.classes:
            issues.append(
                DataIssue(
                    Severity.ERROR,
                    "linea_clase_inexistente",
                    f"La lección {lesson_number}, línea {index}, usa la clase "
                    f"{cid!r}, que no existe.",
                    EntityKind.CLASS,
                    cid,
                    lesson_number,
                )
            )
    if line.student_group is not None and line.student_group not in ids.student_groups:
        issues.append(
            DataIssue(
                Severity.WARNING,
                "linea_grupo_inexistente",
                f"La lección {lesson_number}, línea {index}, usa el grupo "
                f"{line.student_group!r}, que no existe.",
                EntityKind.STUDENT_GROUP,
                line.student_group,
                lesson_number,
            )
        )
    if line.room is not None and line.room not in ids.rooms:
        issues.append(
            DataIssue(
                Severity.WARNING,
                "linea_aula_inexistente",
                f"La lección {lesson_number}, línea {index}, usa el aula "
                f"{line.room!r}, que no existe.",
                EntityKind.ROOM,
                line.room,
                lesson_number,
            )
        )
    if not line.classes and line.student_group is None:
        issues.append(
            DataIssue(
                Severity.WARNING,
                "linea_sin_alumnos",
                f"La lección {lesson_number}, línea {index}, no tiene clases ni grupo de alumnos.",
                lesson_number=lesson_number,
            )
        )

    return issues


def _check_lessons(project: UntisProject) -> list[DataIssue]:
    """Números repetidos, rejillas inexistentes, dobles imposibles."""
    issues: list[DataIssue] = []
    grids = project.grid_by_id
    ids = _Ids.of(project)
    numeros: set[int] = set()

    for le in project.lessons:
        if le.number in numeros:
            issues.append(
                DataIssue(
                    Severity.ERROR,
                    "leccion_duplicada",
                    f"El nº de lección {le.number} está repetido.",
                    lesson_number=le.number,
                )
            )
        numeros.add(le.number)

        if le.ignore:
            continue

        if le.periods_per_week == 0:
            issues.append(
                DataIssue(
                    Severity.WARNING,
                    "leccion_sin_horas",
                    f"La lección {le.number} no tiene períodos por semana.",
                    lesson_number=le.number,
                )
            )

        if le.time_grid and le.time_grid not in grids:
            issues.append(
                DataIssue(
                    Severity.ERROR,
                    "leccion_rejilla_inexistente",
                    f"La lección {le.number} apunta a la rejilla {le.time_grid!r}, que no existe.",
                    lesson_number=le.number,
                )
            )

        for idx, line in enumerate(le.lines):
            issues.extend(_check_lesson_line(ids, le.number, idx, line))

        minimo = le.double_periods.min
        if minimo is not None and minimo * 2 > le.periods_per_week:
            issues.append(
                DataIssue(
                    Severity.ERROR,
                    "dobles_imposibles",
                    f"La lección {le.number} exige {minimo} períodos dobles pero "
                    f"solo tiene {le.periods_per_week} períodos/semana.",
                    lesson_number=le.number,
                )
            )

    return issues


def _check_class_load(project: UntisProject) -> list[DataIssue]:
    """Ninguna clase puede pedir más períodos de los que ofrece su rejilla."""
    issues: list[DataIssue] = []
    carga: defaultdict[str, int] = defaultdict(int)
    for le in project.active_lessons:
        for cid in le.classes:
            carga[cid] += le.periods_per_week

    capacidad = {g.id: len(g.slots()) for g in project.time_grids}
    clases = project.class_by_id
    for cid in sorted(carga):
        clase = clases.get(cid)
        if clase is None:
            continue
        tope = capacidad.get(clase.time_grid)
        if tope is not None and carga[cid] > tope:
            issues.append(
                DataIssue(
                    Severity.ERROR,
                    "clase_sobrecargada",
                    f"La clase {clase.display_name!r} suma {carga[cid]} "
                    f"períodos/semana pero su rejilla solo ofrece {tope}.",
                    EntityKind.CLASS,
                    cid,
                )
            )
    return issues


def _open_cells(project: UntisProject) -> dict[str, set[tuple[int, int]]]:
    """Celdas lectivas que cada clase tiene abiertas: su rejilla menos los -3."""
    vetos: defaultdict[str, list[TimeRequest]] = defaultdict(list)
    for r in project.time_requests:
        if r.entity_kind is EntityKind.CLASS and r.is_block:
            vetos[r.entity_id].append(r)
    grids = {g.id: g for g in project.time_grids}
    abiertas: dict[str, set[tuple[int, int]]] = {}
    for clase in project.classes:
        grid = grids.get(clase.time_grid)
        if grid is None:
            continue
        reglas = vetos.get(clase.id, ())
        abiertas[clase.id] = {
            (d, p) for d, p in grid.slots() if not any(r.covers(d, p) for r in reglas)
        }
    return abiertas


def _check_class_frame(project: UntisProject) -> list[DataIssue]:
    """Marco horario de cada clase: horas abiertas frente a horas que necesita.

    Es el aviso que evita el caso más típico al empezar de cero: dejar la
    jornada entera abierta y que el generador coloque clase a horas en las que
    el colegio ya no da servicio, o al revés, cerrar tanto que no quepa.
    """
    issues: list[DataIssue] = []
    carga: defaultdict[str, int] = defaultdict(int)
    for le in project.active_lessons:
        for cid in le.classes:
            carga[cid] += le.periods_per_week
    abiertas = _open_cells(project)
    clases = project.class_by_id
    for cid in sorted(carga):
        clase = clases.get(cid)
        if clase is None or cid not in abiertas:
            continue
        libres = len(abiertas[cid])
        necesita = carga[cid]
        if necesita > libres:
            issues.append(
                DataIssue(
                    Severity.ERROR,
                    "marco_horario_insuficiente",
                    f"La clase {clase.display_name!r} necesita {necesita} períodos/semana "
                    f"y solo tiene {libres} horas abiertas: amplía su marco horario "
                    f"o quita deseos -3.",
                    EntityKind.CLASS,
                    cid,
                )
            )
        elif libres >= necesita + 5 and libres >= necesita * 1.25:
            issues.append(
                DataIssue(
                    Severity.WARNING,
                    "marco_horario_abierto",
                    f"La clase {clase.display_name!r} tiene {libres} horas abiertas y solo "
                    f"necesita {necesita}: si su jornada termina antes, ciérrala en Deseos "
                    f"de tiempo (marco horario).",
                    EntityKind.CLASS,
                    cid,
                )
            )
    return issues


def _check_short_periods(project: UntisProject) -> list[DataIssue]:
    """Horas mucho más cortas que las demás y abiertas para muchas clases."""
    issues: list[DataIssue] = []
    abiertas = _open_cells(project)
    por_clase: defaultdict[str, str] = defaultdict(str)
    for clase in project.classes:
        por_clase[clase.id] = clase.time_grid
    for grid in project.time_grids:
        lectivas = grid.teaching_periods
        if len(lectivas) < 2:
            continue
        habitual = max(
            {p.duration for p in lectivas},
            key=lambda d: sum(1 for p in lectivas if p.duration == d),
        )
        cortas = [p for p in lectivas if p.duration * 2 <= habitual]
        for corta in cortas:
            cuantas = sum(
                1
                for cid, celdas in abiertas.items()
                if por_clase[cid] == grid.id and any(p == corta.number for _d, p in celdas)
            )
            if cuantas:
                issues.append(
                    DataIssue(
                        Severity.WARNING,
                        "hora_corta_abierta",
                        f"La hora {corta.number} de la rejilla {grid.display_name!r} dura "
                        f"{corta.duration} min frente a los {habitual} habituales y está "
                        f"abierta para {cuantas} clase(s): ciérrala si solo es para "
                        f"dirección de grupo.",
                    )
                )
    return issues


def _check_time_requests(project: UntisProject) -> list[DataIssue]:
    """Una celda no puede ser a la vez imposible (-3) y muy deseable (+3)."""
    issues: list[DataIssue] = []
    duros: defaultdict[tuple[EntityKind, str, int, int], set[int]] = defaultdict(set)
    for r in project.time_requests:
        if r.value in (REQUEST_MIN, REQUEST_MAX) and r.day is not None and r.period is not None:
            duros[(r.entity_kind, r.entity_id, r.day, r.period)].add(r.value)

    for clave in sorted(duros, key=lambda k: (k[0].value, k[1], k[2], k[3])):
        kind, eid, day, period = clave
        if len(duros[clave]) > 1:
            issues.append(
                DataIssue(
                    Severity.ERROR,
                    "deseo_contradictorio",
                    f"{kind.value} {eid!r} tiene deseos duros opuestos en "
                    f"(día {day}, período {period}).",
                    kind,
                    eid,
                )
            )
    return issues


def diagnose_data(project: UntisProject) -> list[DataIssue]:
    """Revisa el proyecto entero y devuelve los hallazgos, errores primero."""
    issues: list[DataIssue] = [
        *_check_master_data(project),
        *_check_room_chains(project),
        *_check_lessons(project),
        *_check_class_load(project),
        *_check_class_frame(project),
        *_check_short_periods(project),
        *_check_time_requests(project),
    ]
    issues.sort(key=lambda i: (not i.is_error, i.code, i.entity_id, i.lesson_number or 0))
    return issues
