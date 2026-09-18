"""Deducción de recreos para rejillas importadas sin marca de pausa.

El XmlInterface de Untis lista todos los períodos de la rejilla, incluidos los
recreos, sin decir cuáles lo son. Sin esa marca, un recreo libre entre dos
clases cuenta como hueco, y la optimización intentaría absurdamente evitar dar
clase antes y después del recreo.

Regla (conservadora y corregible en la ventana Rejilla): un período **más corto
que el período lectivo dominante de su rejilla** en el que **ninguna clase tiene
lección** en el horario de referencia es un recreo. Nunca se marca un período
que aloja una lección con alumnos; las obligaciones no lectivas (p. ej. la
vigilancia de recreo) no cuentan como uso.

Medido sobre el export real 2025-2026: los recreos de 20 min quedan marcados en
todas las rejillas, mientras que los períodos cortos de dirección de grupo
(10-30 min, con 20-100 lecciones cada uno) siguen siendo lectivos.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from .common import PeriodKind
from .lessons import Lesson
from .project import UntisProject
from .time_grid import TimeGrid
from .timetable import Timetable


def _has_students(lesson: Lesson) -> bool:
    return any(line.classes or line.student_group for line in lesson.lines)


def used_periods(project: UntisProject, timetable: Timetable) -> set[tuple[str, int]]:
    """`(rejilla, período)` en los que alguna lección con alumnos está colocada."""
    lecciones = project.lesson_by_number
    usados: set[tuple[str, int]] = set()
    for a in timetable.assignments:
        le = lecciones.get(a.lesson_number)
        if le is not None and _has_students(le):
            usados.add((le.time_grid, a.period))
    return usados


def dominant_duration(grid: TimeGrid) -> int | None:
    """Duración más frecuente de los períodos de la rejilla (min)."""
    conteo = Counter(p.duration for p in grid.periods)
    return conteo.most_common(1)[0][0] if conteo else None


def infer_breaks(project: UntisProject, timetable: Timetable | None = None) -> UntisProject:
    """Copia del proyecto con los recreos deducidos marcados como `BREAK`.

    `timetable` es el horario de referencia; por defecto, el primero del
    proyecto. Sin horario no hay evidencia de uso y el proyecto se devuelve
    intacto. Los períodos ya marcados como recreo se respetan.
    """
    referencia = timetable if timetable is not None else next(iter(project.timetables), None)
    if referencia is None:
        return project
    usados = used_periods(project, referencia)
    rejillas: list[TimeGrid] = []
    for g in project.time_grids:
        dominante = dominant_duration(g)
        periodos = tuple(
            replace(p, kind=PeriodKind.BREAK)
            if (
                dominante is not None
                and p.kind is PeriodKind.LESSON
                and p.duration < dominante
                and (g.id, p.number) not in usados
            )
            else p
            for p in g.periods
        )
        rejillas.append(replace(g, periods=periodos))
    return replace(project, time_grids=tuple(rejillas))


def breaks_of(project: UntisProject) -> dict[str, tuple[int, ...]]:
    """Períodos marcados como recreo en cada rejilla."""
    return {
        g.id: tuple(p.number for p in g.periods if p.kind is PeriodKind.BREAK)
        for g in project.time_grids
    }
