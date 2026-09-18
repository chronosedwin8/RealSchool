"""Ida y vuelta entre el horario Untis (`Timetable`) y la `Solution` canónica.

- `timetable_to_solution`: lleva un horario (el publicado por Untis, uno de la
  heurística o uno editado a mano) al modelo canónico para que el
  `ValidationEngine` —el juez independiente— lo examine.
- `solution_to_timetable`: devuelve al vocabulario Untis lo que produjo CP-SAT.

Las sesiones de una lección se emparejan con sus celdas **por duración**, no
por posición: un horario distinto del de referencia puede ordenar las celdas de
otra forma, y una sesión de 45 min nunca debe caer en un período de 10.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from scheduling_platform.core import (
    Assignment as CanonicalAssignment,
)
from scheduling_platform.core import (
    ResourceId,
    Solution,
    TaskId,
    TimeSlotIndex,
)
from scheduling_platform.untis_model import Assignment, Lesson, Timetable
from scheduling_platform.untis_model.sessions import reference_cells

from .translate import (
    ResourceKind,
    SessionRef,
    Translation,
    reference_line_rooms,
    reference_rooms,
)


@dataclass(frozen=True, slots=True)
class Rebuilt:
    """Resultado de llevar un horario Untis al modelo canónico."""

    solution: Solution
    unplaced: tuple[SessionRef, ...] = field(default_factory=tuple)
    """Sesiones traducidas que el horario no coloca."""
    mismatched: tuple[tuple[int, int, int], ...] = field(default_factory=tuple)
    """Celdas `(lección, día, período)` sin sesión compatible (p. ej. otra duración)."""
    not_translated: tuple[int, ...] = field(default_factory=tuple)
    """Lecciones colocadas en el horario que la traducción excluyó (obligaciones)."""


def _period_duration(tr: Translation, lesson: Lesson, period: int) -> int | None:
    grid = tr.project.grid_by_id.get(lesson.time_grid)
    if grid is None:
        return None
    p = grid.period(period)
    return p.duration if p is not None else None


def timetable_to_solution(tr: Translation, timetable: Timetable) -> Rebuilt:
    """Convierte un horario Untis en una `Solution` canónica."""
    lecciones = tr.project.lesson_by_number
    celdas = reference_cells(timetable)
    aulas = reference_rooms(timetable)

    # Sesiones de cada lección agrupadas por duración, en orden de sesión.
    por_duracion: defaultdict[tuple[int, int], list[SessionRef]] = defaultdict(list)
    for ref in sorted(tr.task_of, key=lambda r: (r.lesson, r.session)):
        por_duracion[(ref.lesson, tr.durations[ref])].append(ref)

    asignaciones: list[CanonicalAssignment] = []
    colocadas: set[SessionRef] = set()
    desparejadas: list[tuple[int, int, int]] = []

    traducidas = {ref.lesson for ref in tr.task_of}
    excluidas: list[int] = []
    for numero, lista in sorted(celdas.items()):
        leccion = lecciones.get(numero)
        if leccion is None:
            continue
        if numero not in traducidas:
            excluidas.append(numero)
            continue
        libres: dict[int, list[SessionRef]] = {}
        for dia, periodo in lista:
            duracion = _period_duration(tr, leccion, periodo)
            if duracion is None:
                desparejadas.append((numero, dia, periodo))
                continue
            cola = libres.setdefault(duracion, list(por_duracion.get((numero, duracion), [])))
            if not cola:
                desparejadas.append((numero, dia, periodo))
                continue
            ref = cola.pop(0)
            grid = tr.project.grid_by_id[leccion.time_grid]
            inicio = grid.period(periodo)
            assert inicio is not None  # garantizado por _period_duration
            recursos = _resources_for(tr, leccion, aulas.get((numero, dia, periodo), ()))
            asignaciones.append(
                CanonicalAssignment(
                    TaskId(tr.task_of[ref]),
                    TimeSlotIndex(tr.clock.slot(dia, inicio.start)),
                    tuple(ResourceId(r) for r in sorted(set(recursos))),
                )
            )
            colocadas.add(ref)

    sin_colocar = tuple(
        ref
        for ref in sorted(tr.task_of, key=lambda r: (r.lesson, r.session))
        if ref not in colocadas
    )
    solucion = Solution(assignments=tuple(asignaciones), objective_value=0)
    return Rebuilt(solucion, sin_colocar, tuple(desparejadas), tuple(excluidas))


def _resources_for(tr: Translation, leccion: Lesson, rooms: tuple[str, ...]) -> list[int]:
    """Profesores, clases y aulas que ocupa una sesión del acople."""
    rid = tr.rid_of
    recursos = [
        rid[(ResourceKind.TEACHER, t)] for t in leccion.teachers if (ResourceKind.TEACHER, t) in rid
    ]
    recursos += [
        rid[(ResourceKind.CLASS, c)] for c in leccion.classes if (ResourceKind.CLASS, c) in rid
    ]
    recursos += [rid[(ResourceKind.ROOM, r)] for r in rooms if (ResourceKind.ROOM, r) in rid]
    return recursos


def solution_to_timetable(
    tr: Translation,
    solution: Solution,
    *,
    timetable_id: str,
    name: str = "",
    reference: Timetable | None = None,
) -> Timetable:
    """Devuelve una `Solution` canónica al vocabulario Untis.

    Si `reference` coloca la misma lección en la misma celda con el mismo
    conjunto de aulas, se conserva su reparto línea -> aula; así la ida y vuelta
    de un horario no baraja las aulas entre las líneas de un acople.
    """
    lecciones = tr.project.lesson_by_number
    lineas_ref = reference_line_rooms(reference)
    resultado: list[Assignment] = []

    for a in solution.assignments:
        ref = tr.session_of[int(a.task_id)]
        leccion = lecciones[ref.lesson]
        dia, minuto = tr.clock.decode(int(a.start))
        grid = tr.project.grid_by_id[leccion.time_grid]
        periodo = next(
            (p.number for p in grid.periods if p.start == minuto),
            None,
        )
        if periodo is None:
            raise ValueError(
                f"La tarea {int(a.task_id)} empieza a las {minuto} min, que no es inicio "
                f"de ningún período de la rejilla {leccion.time_grid!r}"
            )
        elegidas = [
            tr.entity_of[int(r)][1]
            for r in a.resource_ids
            if tr.entity_of[int(r)][0] is ResourceKind.ROOM
        ]
        reparto = _rooms_by_line(
            len(leccion.lines), elegidas, lineas_ref.get((ref.lesson, dia, periodo), {})
        )
        for linea in range(len(leccion.lines)):
            resultado.append(
                Assignment(
                    lesson_number=ref.lesson,
                    line=linea,
                    day=dia,
                    period=periodo,
                    room=reparto.get(linea),
                )
            )

    resultado.sort(key=lambda x: (x.lesson_number, x.day, x.period, x.line))
    return Timetable(id=timetable_id, name=name, assignments=tuple(resultado))


def _rooms_by_line(n_lines: int, chosen: list[str], previous: dict[int, str]) -> dict[int, str]:
    """Reparte las aulas elegidas entre las líneas del acople.

    - Mismo conjunto de aulas que la referencia: se respeta su reparto exacto.
    - Otro conjunto: las aulas van primero a las líneas que ya tenían aula en la
      referencia (en su orden) y, si sobran, a las demás líneas en orden.
    """
    if previous and set(previous.values()) == set(chosen):
        return dict(previous)
    lineas = [ln for ln in sorted(previous) if ln < n_lines]
    lineas += [ln for ln in range(n_lines) if ln not in previous]
    return dict(zip(lineas, sorted(chosen), strict=False))
