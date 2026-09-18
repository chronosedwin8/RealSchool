"""Ponderación Untis -> términos de objetivo CP-SAT para una ventana.

Compila los deslizadores de `Weighting` en plugins del puente (`bridge.plugins`)
con la geometría Untis precalculada: qué inicio de cada tarea ocupa qué período
de la rejilla propia de cada clase y profesor, y qué parejas de inicios forman un
período doble. Cada término lleva como etiqueta el criterio de la ponderación, de
modo que `MetricsEngine.breakdown` devuelve el desglose por criterio
(`bridge.objective`).

Cubre, en semántica de períodos idéntica al evaluador de referencia, los huecos
de clase y de profesor (los criterios de más peso) y los períodos dobles. El
resto de criterios los optimiza la heurística; el pulido solo acepta una ventana
si el número de evaluación completo mejora, así que no hace falta que CP-SAT los
vea todos.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise

from scheduling_platform.core import Solution
from scheduling_platform.plugins import SchedulingPlugin
from scheduling_platform.plugins.catalog.structural import IntervalNoOverlapPlugin
from scheduling_platform.untis_model import Lesson, TimeGrid, Weighting
from scheduling_platform.untis_model.evaluation import Evaluator

from .plugins import GapEntity, MinimalChangePlugin, MinPairsPlugin, PeriodGapsPlugin, Placement
from .translate import Translation

#: Criterios de la ponderación que CP-SAT sabe expresar en una ventana.
CP_CRITERIA: tuple[str, ...] = ("class_gaps", "teacher_gaps", "subject_double_periods")


@dataclass(frozen=True, slots=True)
class Geometry:
    """Intervalos de reloj de cada colocación posible, precalculados una vez."""

    tr: Translation
    starts: dict[int, tuple[tuple[int, int, int, int], ...]]
    """`tarea -> ((inicio canónico, día, min_inicio, min_fin), ...)`."""

    @classmethod
    def of(cls, tr: Translation) -> Geometry:
        inicios: dict[int, tuple[tuple[int, int, int, int], ...]] = {}
        for task in tr.problem.tasks:
            filas = []
            for s in sorted(task.allowed_starts or ()):
                dia, minuto = tr.clock.decode(int(s))
                filas.append((int(s), dia, minuto, minuto + task.duration))
            inicios[int(task.id)] = tuple(filas)
        return cls(tr, inicios)

    def covering(
        self, tasks: list[int], grid: TimeGrid
    ) -> tuple[tuple[tuple[Placement, ...], ...], ...]:
        """Por día y período lectivo de `grid`: colocaciones de `tasks` que lo ocupan."""
        periodos = grid.teaching_periods
        resultado: list[tuple[tuple[Placement, ...], ...]] = []
        for dia in sorted(grid.days):
            fila: list[tuple[Placement, ...]] = []
            for p in periodos:
                fila.append(
                    tuple(
                        (t, s)
                        for t in tasks
                        for s, d, ini, fin in self.starts[t]
                        if d == dia and ini < p.end and p.start < fin
                    )
                )
            resultado.append(tuple(fila))
        return tuple(resultado)

    def fixed_busy(
        self, frozen: list[tuple[int, int]], grid: TimeGrid
    ) -> tuple[tuple[bool, ...], ...]:
        """Por día y período: ocupado por alguna colocación congelada `(tarea, inicio)`."""
        intervalos: defaultdict[int, list[tuple[int, int]]] = defaultdict(list)
        for tarea, inicio in frozen:
            dia, minuto = self.tr.clock.decode(inicio)
            duracion = self.tr.durations[self.tr.session_of[tarea]]
            intervalos[dia].append((minuto, minuto + duracion))
        return tuple(
            tuple(
                any(ini < p.end and p.start < fin for ini, fin in intervalos.get(dia, ()))
                for p in grid.teaching_periods
            )
            for dia in sorted(grid.days)
        )


def next_start(tr: Translation, lesson: Lesson) -> dict[int, int]:
    """Inicio canónico -> inicio del período lectivo contiguo, el mismo día."""
    grid = tr.project.grid_by_id.get(lesson.time_grid)
    if grid is None:
        return {}
    lectivos = grid.teaching_periods
    siguiente: dict[int, int] = {}
    for dia in grid.days:
        for a, b in pairwise(lectivos):
            if b.number == a.number + 1:
                siguiente[tr.clock.slot(dia, a.start)] = tr.clock.slot(dia, b.start)
    return siguiente


def window_plugins(
    tr: Translation,
    geo: Geometry,
    ev: Evaluator,
    base: Solution,
    window: set[int],
    clase: str,
    weighting: Weighting,
) -> list[SchedulingPlugin]:
    lecciones = tr.project.lesson_by_number
    inicio_de = {int(a.task_id): int(a.start) for a in base.assignments}

    def involucra(tarea: int, kind: str, ident: str) -> bool:
        le = lecciones[tr.session_of[tarea].lesson]
        return ident in (le.classes if kind == "class" else le.teachers)

    entidades: list[GapEntity] = []
    grid_clase = ev.class_grid[clase]
    propias = [t for t in window if involucra(t, "class", clase)]
    congeladas = [
        (t, s) for t, s in inicio_de.items() if t not in window and involucra(t, "class", clase)
    ]
    entidades.append(
        GapEntity(
            key=f"c{clase}",
            label="class_gaps",
            weight=weighting.weight("class_gaps"),
            days=geo.covering(propias, grid_clase),
            fixed_busy=geo.fixed_busy(congeladas, grid_clase),
        )
    )
    profes = sorted(
        {t for tarea in window for t in lecciones[tr.session_of[tarea].lesson].teachers}
    )
    for profe in profes:
        grid = ev.teacher_grid.get(profe)
        if grid is None:
            continue
        suyas = [t for t in window if involucra(t, "teacher", profe)]
        fijas = [
            (t, s)
            for t, s in inicio_de.items()
            if t not in window and involucra(t, "teacher", profe)
        ]
        entidades.append(
            GapEntity(
                key=f"t{profe}",
                label="teacher_gaps",
                weight=weighting.weight("teacher_gaps"),
                days=geo.covering(suyas, grid),
                fixed_busy=geo.fixed_busy(fijas, grid),
            )
        )

    plugins: list[SchedulingPlugin] = [
        IntervalNoOverlapPlugin(),
        PeriodGapsPlugin(entities=tuple(entidades)),
    ]

    # Períodos dobles de las lecciones de la ventana.
    por_leccion: defaultdict[int, list[int]] = defaultdict(list)
    for t in window:
        por_leccion[tr.session_of[t].lesson].append(t)
    requisitos: list[tuple[int, tuple[tuple[Placement, Placement], ...]]] = []
    for numero, tareas in sorted(por_leccion.items()):
        le = lecciones[numero]
        minimo = le.double_periods.min
        if not minimo or len(tareas) < 2:
            continue
        siguiente = next_start(tr, le)
        combos = tuple(
            ((i, s), (j, siguiente[s]))
            for i in tareas
            for j in tareas
            if i != j
            for s, *_ in geo.starts[i]
            if s in siguiente and any(x[0] == siguiente[s] for x in geo.starts[j])
        )
        requisitos.append((minimo, combos))
    if requisitos:
        plugins.append(
            MinPairsPlugin(
                requirements=tuple(requisitos), weight=weighting.weight("subject_double_periods")
            )
        )

    plugins.append(
        MinimalChangePlugin(
            original=tuple((t, inicio_de[t]) for t in sorted(window) if t in inicio_de),
            weight=1,
            room_weight=1,
        )
    )
    return plugins


__all__ = ["CP_CRITERIA", "Geometry", "next_start", "window_plugins"]
