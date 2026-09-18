"""Heurística (R3) sobre el export real seudonimizado del Colegio Alemán.

8 rejillas con horas distintas, ~1.676 sesiones lectivas, 722 lecciones y
acoples de hasta 10 líneas. Se comparan los resultados con el horario que
publicó Untis, evaluado con la misma ponderación (la por defecto) y los
recreos deducidos.
"""

from __future__ import annotations

import random
import time
from collections import Counter
from pathlib import Path

import pytest

from scheduling_platform.heuristic import Strategy, build_model, optimize
from scheduling_platform.heuristic.difficulty import lesson_difficulty
from scheduling_platform.heuristic.incremental import State
from scheduling_platform.heuristic.placement import lesson_order, load_reference, session_order
from scheduling_platform.interop.xml import read_xml
from scheduling_platform.untis_model import Timetable, UntisProject
from scheduling_platform.untis_model.breaks import infer_breaks
from scheduling_platform.untis_model.evaluation import Evaluator, Report

from .test_heuristic import assert_matches_evaluator, hard_violations, random_moves


@pytest.fixture(scope="module")
def project(anon_xml_path: Path) -> UntisProject:
    return infer_breaks(read_xml(anon_xml_path))


def _lective_sessions(project: UntisProject) -> int:
    return sum(
        le.periods_per_week
        for le in project.active_lessons
        if any(line.classes or line.student_group for line in le.lines)
    )


def _summary(name: str, rep: Report, elapsed: float | None = None) -> str:
    e = rep.evaluation
    choques = Counter(c.kind for c in rep.clashes)
    top = ", ".join(f"{s.criterion}={s.violations}x{s.weight}" for s in e.by_contribution()[:4])
    tiempo = f"{elapsed:6.1f}s " if elapsed is not None else "        "
    return (
        f"{name:<8} {tiempo}sin colocar={e.unplaced_periods:<3} choques={dict(choques)} "
        f"blandos={e.soft_points:<7} total={e.total:<8} [{top}]"
    )


def test_equivalencia_real_tras_cada_movimiento(project: UntisProject) -> None:
    ref = project.timetables[0]
    model = build_model(project, ref, project.weighting)
    state = State(model)
    ev = Evaluator(project)
    orden = session_order(model, lesson_order(model, lesson_difficulty(model), random.Random(0)))
    load_reference(state, orden)
    assert_matches_evaluator(state, ev, project.weighting)
    rng = random.Random(7)

    def check() -> None:
        assert_matches_evaluator(state, ev, project.weighting)

    assert random_moves(state, rng, 150, check) >= 20
    assert random_moves(state, rng, 6000) > 1000
    assert_matches_evaluator(state, ev, project.weighting)


def test_estrategia_a_real_frente_a_untis(project: UntisProject) -> None:
    ev = Evaluator(project)
    untis = ev.report(project.timetables[0])
    result = optimize(project, strategy=Strategy.A, time_limit=20)
    rep = ev.report(result.timetable)
    print()
    print(_summary("Untis", untis))
    print(_summary("A (20s)", rep, result.elapsed))
    print(f"iteraciones={result.iterations} ({result.iterations / result.elapsed:.0f}/s)")
    assert result.evaluation == rep.evaluation
    assert hard_violations(rep.clashes) == []
    assert result.evaluation.unplaced_periods <= 0.02 * _lective_sessions(project)
    # Con la misma ponderación, A ya mejora el número de evaluación publicado.
    assert result.evaluation.total < untis.evaluation.total
    assert result.elapsed < 25


def _moved_sessions(reference: Timetable, result: Timetable) -> int:
    """Sesiones del resultado que no están en una celda de referencia de su lección."""
    ref = {(a.lesson_number, a.day, a.period) for a in reference.assignments if a.line == 0}
    nuevas = {(a.lesson_number, a.day, a.period) for a in result.assignments if a.line == 0}
    return len(nuevas - ref)


def test_reparar_resuelve_los_choques_de_untis_moviendo_poco(project: UntisProject) -> None:
    ref = project.timetables[0]
    ev = Evaluator(project)
    antes = ev.report(ref)
    assert Counter(c.kind for c in antes.clashes)["teacher"] == 7
    result = optimize(project, strategy=Strategy.REPAIR, time_limit=5)
    despues = ev.report(result.timetable)
    movidas = _moved_sessions(ref, result.timetable)
    print()
    print(_summary("Untis", antes))
    print(_summary("REPARAR", despues, result.elapsed))
    print(f"sesiones movidas={movidas}")
    assert hard_violations(despues.clashes) == []
    assert despues.evaluation.unplaced_periods <= antes.evaluation.unplaced_periods
    assert movidas <= 20
    assert result.elapsed < 8


def test_parada_rapida_en_el_proyecto_real(project: UntisProject) -> None:
    inicio = time.perf_counter()
    result = optimize(
        project,
        strategy=Strategy.B,
        time_limit=600,
        should_stop=lambda: time.perf_counter() - inicio > 0.5,
    )
    assert time.perf_counter() - inicio < 3.0
    assert hard_violations(Evaluator(project).report(result.timetable).clashes) == []
