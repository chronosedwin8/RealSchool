"""Estrategia "Reparar": CP-SAT con cambio mínimo sobre una ventana (`bridge.repair`)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from scheduling_platform.bridge import translate
from scheduling_platform.bridge.plugins import MinimalChangePlugin
from scheduling_platform.bridge.rebuild import timetable_to_solution
from scheduling_platform.bridge.repair import conflicting_tasks, repair
from scheduling_platform.interop.xml import read_xml
from scheduling_platform.untis_model import (
    Assignment,
    Lesson,
    LessonLine,
    PeriodDef,
    SchoolClass,
    Subject,
    Teacher,
    TimeGrid,
    Timetable,
    UntisProject,
)
from scheduling_platform.untis_model.breaks import infer_breaks
from scheduling_platform.untis_model.evaluation import Evaluator


def _grid() -> TimeGrid:
    return TimeGrid(
        id="G",
        days=(1, 2),
        periods=tuple(PeriodDef(n, 480 + (n - 1) * 50, 480 + (n - 1) * 50 + 45) for n in (1, 2, 3)),
    )


def _leccion(n: int, profe: str, clase: str, per: int = 1) -> Lesson:
    return Lesson(
        number=n,
        lines=(LessonLine(subject="MAT", teacher=profe, classes=(clase,)),),
        periods_per_week=per,
        time_grid="G",
    )


def _proyecto(
    lecciones: tuple[Lesson, ...], celdas: dict[int, list[tuple[int, int]]]
) -> UntisProject:
    tt = Timetable(
        id="t",
        assignments=tuple(Assignment(n, 0, d, p) for n, cs in celdas.items() for d, p in cs),
    )
    return UntisProject(
        time_grids=(_grid(),),
        classes=(SchoolClass(id="C1", time_grid="G"), SchoolClass(id="C2", time_grid="G")),
        teachers=(Teacher(id="T1"), Teacher(id="T2")),
        subjects=(Subject(id="MAT"),),
        lessons=lecciones,
        timetables=(tt,),
    )


def _choques(p: UntisProject, tt: Timetable) -> int:
    return sum(1 for c in Evaluator(p).report(tt).clashes if c.kind != "time_request")


# --------------------------------------------------------------------------- #
# Sintéticos
# --------------------------------------------------------------------------- #


def test_nada_que_reparar() -> None:
    p = _proyecto((_leccion(1, "T1", "C1"),), {1: [(1, 1)]})
    out = repair(p, p.timetables[0], time_limit=10)
    assert out.status == "nothing_to_do" and out.ok
    assert out.timetable == p.timetables[0]


def test_choque_de_profesor_mueve_una_sola_sesion() -> None:
    p = _proyecto(
        (_leccion(1, "T1", "C1", per=2), _leccion(2, "T1", "C2")),
        {1: [(1, 1), (1, 2)], 2: [(1, 1)]},
    )
    assert _choques(p, p.timetables[0]) == 1
    out = repair(p, p.timetables[0], time_limit=10)
    assert out.status == "repaired"
    assert len(out.moved) == 1
    assert _choques(p, out.timetable) == 0


def test_coloca_sesiones_sin_colocar() -> None:
    p = _proyecto((_leccion(1, "T1", "C1", per=2),), {1: [(1, 1)]})
    out = repair(p, p.timetables[0], time_limit=10)
    assert out.status == "repaired"
    assert len(out.placed) == 1
    assert Evaluator(p).evaluate(out.timetable).unplaced_periods == 0


def test_sin_hueco_posible_es_infactible() -> None:
    # 7 sesiones de una clase en una rejilla de 2 días x 3 períodos = 6 celdas.
    p = _proyecto((_leccion(1, "T1", "C1", per=7),), {1: [(1, 1)]})
    out = repair(p, p.timetables[0], time_limit=10, max_rounds=2)
    assert out.status in ("infeasible", "partial")
    assert not out.ok


def test_parada_cooperativa() -> None:
    p = _proyecto(
        (_leccion(1, "T1", "C1", per=2), _leccion(2, "T1", "C2")),
        {1: [(1, 1), (1, 2)], 2: [(1, 1)]},
    )
    out = repair(p, p.timetables[0], time_limit=10, should_stop=lambda: True)
    assert out.status == "cancelled"


def test_conflictos_sobre_la_solucion_canonica() -> None:
    p = _proyecto((_leccion(1, "T1", "C1"), _leccion(2, "T1", "C2")), {1: [(1, 1)], 2: [(1, 1)]})
    tr = translate(p)
    sol = timetable_to_solution(tr, p.timetables[0]).solution
    assert len(conflicting_tasks(tr.problem, sol)) == 2


def test_plugin_de_cambio_minimo_ignora_inicios_invalidos() -> None:
    p = _proyecto((_leccion(1, "T1", "C1"),), {1: [(1, 1)]})
    tr = translate(p)
    from scheduling_platform.plugins import SchedulingModelContext

    ctx = SchedulingModelContext.build(tr.problem)
    tarea = next(iter(tr.task_of.values()))
    valido = ctx.valid_starts(tarea)[0]
    aporte = MinimalChangePlugin(original=((tarea, valido), (tarea, 10**6))).contribute(ctx)
    assert len(aporte.penalties) == 1


# --------------------------------------------------------------------------- #
# Export real: los 7 choques del horario publicado por Untis
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def anon(anon_xml_path: Path) -> UntisProject:
    return infer_breaks(read_xml(anon_xml_path))


def test_real_repara_los_siete_choques_de_untis(anon: UntisProject) -> None:
    tt = anon.timetables[0]
    assert _choques(anon, tt) == 7

    t0 = time.perf_counter()
    out = repair(anon, tt, time_limit=30, include_unplaced=False)
    duracion = time.perf_counter() - t0

    assert out.status == "repaired"
    assert _choques(anon, out.timetable) == 0
    assert duracion < 30  # criterio del documento maestro: Reparar <= 30 s
    assert 0 < len(out.moved) <= 10  # cambio mínimo: solo las lecciones en choque
    # Lo que no cambió de hora ni de aula queda idéntico, y el aula casi nunca cambia.
    tocadas = {m.lesson for m in (*out.moved, *out.rerouted)}
    intactas = {a for a in tt.assignments if a.lesson_number not in tocadas}
    assert intactas <= set(out.timetable.assignments)
    assert len(out.rerouted) <= 2
