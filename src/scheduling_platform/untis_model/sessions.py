"""Sesiones de una lección y la duración de cada una.

Una lección de N períodos/semana son N **sesiones**; cada sesión ocupa un
período de la rejilla de la lección. Los períodos de una rejilla no duran lo
mismo (dirección de grupo de 10 min, clases de 45, un bloque de 60...).

Como en Untis, la heurística coloca una sesión en **cualquier** período lectivo
de su rejilla; qué va en cada período lo deciden los deseos de tiempo (ADR-039).
El puente, en cambio, necesita una duración fija por `Task` (el motor mide el
tiempo en minutos para detectar choques entre rejillas distintas): la toma del
período donde la sesión está colocada en el horario de referencia o, si no está
colocada, de la duración dominante de la rejilla. Así cualquier horario de la
heurística se traduce al modelo canónico con sus duraciones reales.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .lessons import Lesson
from .project import UntisProject
from .time_grid import TimeGrid
from .timetable import Timetable

#: Duración de una sesión cuya rejilla no tiene períodos lectivos (min).
DEFAULT_DURATION = 45


def dominant_teaching_duration(grid: TimeGrid) -> int:
    """Duración más frecuente de los períodos lectivos de la rejilla."""
    conteo = Counter(p.duration for p in grid.teaching_periods)
    return conteo.most_common(1)[0][0] if conteo else DEFAULT_DURATION


def reference_cells(timetable: Timetable | None) -> dict[int, list[tuple[int, int]]]:
    """Celdas `(día, período)` colocadas de cada lección, ordenadas.

    Todas las líneas de un acople comparten celdas, así que basta la línea 0.
    """
    celdas: defaultdict[int, set[tuple[int, int]]] = defaultdict(set)
    if timetable is not None:
        for a in timetable.assignments:
            if a.line == 0:
                celdas[a.lesson_number].add(a.slot)
    return {n: sorted(c) for n, c in celdas.items()}


def session_durations(
    lesson: Lesson, grid: TimeGrid | None, placed: list[tuple[int, int]]
) -> tuple[int, ...]:
    """Duración (min) de cada sesión de la lección, en orden de sesión."""
    dominante = dominant_teaching_duration(grid) if grid is not None else DEFAULT_DURATION
    duraciones: list[int] = []
    for i in range(lesson.periods_per_week):
        periodo = grid.period(placed[i][1]) if grid is not None and i < len(placed) else None
        duraciones.append(periodo.duration if periodo is not None else dominante)
    return tuple(duraciones)


def all_session_durations(
    project: UntisProject, reference: Timetable | None
) -> dict[int, tuple[int, ...]]:
    """`lección -> duraciones de sus sesiones` para las lecciones activas."""
    celdas = reference_cells(reference)
    grids = project.grid_by_id
    return {
        le.number: session_durations(le, grids.get(le.time_grid), celdas.get(le.number, []))
        for le in project.active_lessons
        if le.periods_per_week > 0
    }
