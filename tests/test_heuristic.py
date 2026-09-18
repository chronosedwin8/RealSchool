"""Heurística (R3) sobre un proyecto sintético que ejercita todos los criterios.

La prueba clave es la de **equivalencia**: tras cada movimiento aleatorio, las
violaciones por criterio, los no colocados y el número de evaluación que lleva
`heuristic.State` de forma incremental coinciden exactamente con
`Evaluator.report` sobre el horario resultante.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

import pytest

from scheduling_platform.heuristic import HeuristicResult, Strategy, build_model, optimize
from scheduling_platform.heuristic.incremental import Change, State
from scheduling_platform.heuristic.moves import MoveGenerator
from scheduling_platform.heuristic.placement import construct
from scheduling_platform.untis_model import (
    UNSET,
    Assignment,
    EntityKind,
    HalfDay,
    Lesson,
    LessonLine,
    MinMax,
    PeriodDef,
    PeriodKind,
    Room,
    SchoolClass,
    Subject,
    Teacher,
    TimeGrid,
    TimeRequest,
    Timetable,
    UnspecifiedKind,
    UnspecifiedRequest,
    UntisProject,
    Weighting,
)
from scheduling_platform.untis_model.evaluation import Evaluator
from scheduling_platform.untis_model.sessions import all_session_durations

# --------------------------------------------------------------------------- #
# Proyecto sintético: dos rejillas con horas distintas, recreos, tarde,
# acoples, obligaciones, grupos de alumnos, aulas con cadena y deseos.
# --------------------------------------------------------------------------- #


def _p(n: int, start: int, end: int, *, brk: bool = False, pm: bool = False) -> PeriodDef:
    return PeriodDef(
        n,
        start,
        end,
        kind=PeriodKind.BREAK if brk else PeriodKind.LESSON,
        half_day=HalfDay.AFTERNOON if pm else HalfDay.MORNING,
    )


G1 = TimeGrid(
    id="G1",
    days=(1, 2, 3, 4, 5),
    periods=(
        _p(1, 480, 525),
        _p(2, 530, 575),
        _p(3, 575, 595, brk=True),
        _p(4, 600, 645),
        _p(5, 650, 695),
        _p(6, 700, 745, pm=True),
        _p(7, 750, 795, pm=True),
        _p(8, 800, 810, pm=True),
    ),
)
G2 = TimeGrid(
    id="G2",
    days=(1, 2, 3, 4, 5),
    periods=(
        _p(1, 490, 535),
        _p(2, 540, 585),
        _p(3, 590, 635),
        _p(4, 640, 685),
        _p(5, 700, 745, pm=True),
        _p(6, 750, 795, pm=True),
    ),
)


def _line(
    subject: str,
    teacher: str | None,
    classes: tuple[str, ...] = (),
    *,
    room: str | None = None,
    group: str | None = None,
) -> LessonLine:
    return LessonLine(
        subject=subject, teacher=teacher, classes=classes, room=room, student_group=group
    )


def _lessons() -> tuple[Lesson, ...]:
    return (
        Lesson(1, (_line("MAT", "T1", ("C1",), room="R1"),), 4, "G1"),
        Lesson(2, (_line("ING", "T2", ("C1",), room="R2"),), 3, "G1"),
        Lesson(3, (_line("DEU", "T3", ("C1",)),), 2, "G1", double_periods=MinMax(1, 1)),
        Lesson(4, (_line("ART", "T1", ("C2",)),), 2, "G1"),
        Lesson(5, (_line("SPO", "T4", ("C2",)),), 3, "G1"),
        Lesson(6, (_line("PHY", "T5", ("C3",), room="R3"),), 2, "G2"),
        Lesson(7, (_line("MAT", "T3", ("C3",)),), 4, "G2", not_same_day=True),
        Lesson(
            8,
            (
                _line("ING", "T2", ("C3", "C4")),
                _line("DEU", "T4", ("C3", "C4")),
                _line("ART", None, ("C4",)),
            ),
            2,
            "G2",
        ),
        Lesson(9, (_line("ART", "T5", ("C4",)),), 3, "G2", block=(3,)),
        Lesson(10, (_line("DUT", "T1"),), 2, "G1"),
        Lesson(11, (_line("SPO", "T2", ("C2",)),), 2, "G1", sequence_after="ART"),
        Lesson(12, (_line("MAT", "T4", group="SG1"),), 1, "G1"),
        Lesson(13, (_line("ART", "T3", ("C2",)),), 1, "G1", fixed=True),
        Lesson(14, (_line("MAT", "T1", ("C1",)),), 2, "G1", ignore=True),
        Lesson(15, (_line("ING", "T5", ("C1", "C2"), room="R4"),), 2, "G1"),
        Lesson(16, (_line("MAT", "T1", ("C1",)),), 1, "G1"),
    )


def _reference() -> Timetable:
    celdas: dict[int, list[tuple[int, int]]] = {
        1: [(1, 2), (2, 2), (3, 4), (4, 8)],  # la última sesión dura 10 min
        2: [(1, 4), (3, 1), (5, 5)],
        3: [(2, 4), (2, 5)],
        6: [(1, 1), (3, 2)],
        8: [(2, 3), (4, 3)],
        10: [(1, 3), (2, 6)],  # vigilancia en un recreo
        13: [(4, 1)],
    }
    aulas = {1: "R1", 2: "R2", 6: "R4"}
    lecciones = {le.number: le for le in _lessons()}
    asign = tuple(
        Assignment(n, i, d, p, room=aulas.get(n) if i == 0 else None)
        for n, lista in celdas.items()
        for d, p in lista
        for i in range(len(lecciones[n].lines))
    )
    return Timetable(id="ref", assignments=asign)


def synthetic_project() -> UntisProject:
    return UntisProject(
        time_grids=(G1, G2),
        classes=(
            SchoolClass(
                id="C1",
                time_grid="G1",
                students=25,
                periods_per_day=MinMax(2, 5),
                lunch_break=MinMax(1, None),
                main_subjects_per_day=2,
            ),
            SchoolClass(id="C2", time_grid="G1", students=18),
            SchoolClass(id="C3", time_grid="G2", students=30, periods_per_day=MinMax(1, 4)),
            SchoolClass(id="C4", time_grid="G2"),
        ),
        teachers=(
            Teacher(
                id="T1",
                periods_per_day=MinMax(1, 3),
                ntp_per_day=MinMax(None, 1),
                ntp_per_week=MinMax(None, 2),
                days_per_week_max=3,
                consecutive_max=2,
                lunch_break=MinMax(1, None),
            ),
            Teacher(id="T2", ntp_per_week=MinMax(1, 3)),
            Teacher(id="T3", days_per_week_max=4),
            Teacher(id="T4", consecutive_max=1),
            Teacher(id="T5", periods_per_day=UNSET),
        ),
        rooms=(
            Room(id="R1", capacity=20, alternative_room="R2"),
            Room(id="R2", alternative_room="R3"),
            Room(id="R3", capacity=35),
            Room(id="R4", capacity=40),
        ),
        subjects=(
            Subject(id="MAT", main_subject=True),
            Subject(id="ING", main_subject=True, subject_group="L"),
            Subject(id="DEU", subject_group="L"),
            Subject(id="ART"),
            Subject(id="SPO", not_same_day=True),
            Subject(id="PHY", required_room="R4"),
            Subject(id="DUT"),
        ),
        lessons=_lessons(),
        time_requests=(
            TimeRequest(EntityKind.TEACHER, "T1", -3, day=1, period=1),
            TimeRequest(EntityKind.TEACHER, "T3", -2, day=3),
            TimeRequest(EntityKind.CLASS, "C2", -2, period=7),
            TimeRequest(EntityKind.CLASS, "C4", -1, day=5),
            TimeRequest(EntityKind.ROOM, "R2", -1, day=2),
            TimeRequest(EntityKind.ROOM, "R1", -3, day=3, period=2),
            TimeRequest(EntityKind.SUBJECT, "MAT", -1, day=5),
            TimeRequest(EntityKind.SUBJECT, "ART", -3, day=5, period=7),
            TimeRequest(EntityKind.TEACHER, "T2", 3, day=2, period=2),
        ),
        unspecified_requests=(
            UnspecifiedRequest(EntityKind.TEACHER, "T4", UnspecifiedKind.FREE_DAY, 1),
            UnspecifiedRequest(EntityKind.CLASS, "C1", UnspecifiedKind.FREE_AFTERNOON, 2),
            UnspecifiedRequest(EntityKind.TEACHER, "T5", UnspecifiedKind.FREE_MORNING, 1),
        ),
        timetables=(_reference(),),
    )


#: Todos los deslizadores a 1-3 para que ningún criterio pese 0 en el total.
WEIGHTING = Weighting.from_dict({c: 1 + i % 3 for i, c in enumerate(Weighting.criteria())})


# --------------------------------------------------------------------------- #
# Utilidades de verificación
# --------------------------------------------------------------------------- #


def assert_matches_evaluator(state: State, evaluator: Evaluator, weighting: Weighting) -> None:
    """El estado incremental coincide criterio a criterio con el evaluador."""
    rep = evaluator.report(state.to_timetable("check"), weighting)
    ev = rep.evaluation
    propias = state.violations()
    distintas = {
        s.criterion: (s.violations, propias[s.criterion])
        for s in ev.scores
        if s.violations != propias[s.criterion]
    }
    assert distintas == {}
    assert ev.unplaced_periods == state.unplaced_count()
    assert ev.total == state.evaluation_total
    assert ev.clashes == state.evaluation().clashes
    assert state.recompute_total() == state.total
    assert hard_violations(rep.clashes) == []


def hard_violations(clashes: tuple[object, ...]) -> list[object]:
    """Choques de recurso o celdas -3 (los +3 incumplidos no cuentan: son deseos)."""
    malos: list[object] = []
    for c in clashes:
        kind = getattr(c, "kind", "")
        lessons = getattr(c, "lessons", ())
        if kind in ("teacher", "class", "room") or (kind == "time_request" and lessons):
            malos.append(c)
    return malos


def random_moves(
    state: State,
    rng: random.Random,
    steps: int,
    check: Callable[[], None] | None = None,
) -> int:
    """Aplica `steps` movimientos al azar (acepta o deshace); devuelve los evaluados."""
    gen = MoveGenerator(state, rng)
    m = state.m
    evaluados = 0
    for _ in range(steps):
        tipo = rng.randrange(len(gen.kinds) + 1)
        cambios: list[Change] | None
        if tipo == len(gen.kinds):
            # Quitar una sesión colocada (movimiento de expulsión).
            colocadas = [s for s in gen.movable if state.cell[s] >= 0]
            cambios = [(rng.choice(colocadas), -1, None)] if colocadas else None
        else:
            cambios = gen.kinds[tipo][1]()
        if cambios is None:
            continue
        d = state.apply(cambios)
        if d is None:
            continue
        evaluados += 1
        if rng.random() < 0.3:
            state.undo()
        else:
            state.commit()
            gen.refresh_unplaced()
        if check is not None:
            check()
    assert m is state.m
    return evaluados


# --------------------------------------------------------------------------- #
# Equivalencia incremental == evaluador de referencia
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("seed", range(6))
def test_equivalencia_tras_cada_movimiento(seed: int) -> None:
    project = synthetic_project()
    model = build_model(project, project.timetables[0], WEIGHTING)
    state = State(model)
    ev = Evaluator(project)
    assert_matches_evaluator(state, ev, WEIGHTING)  # horario vacío
    rng = random.Random(seed)
    orden = list(range(model.nsessions))
    rng.shuffle(orden)
    construct(state, orden[: len(orden) * 2 // 3], rng)
    assert_matches_evaluator(state, ev, WEIGHTING)

    def check() -> None:
        assert_matches_evaluator(state, ev, WEIGHTING)

    assert random_moves(state, rng, 250, check) > 20


def test_equivalencia_al_final_de_una_secuencia_larga() -> None:
    project = synthetic_project()
    model = build_model(project, project.timetables[0], WEIGHTING)
    state = State(model)
    rng = random.Random(99)
    construct(state, list(range(model.nsessions)), rng)
    assert random_moves(state, rng, 20_000) > 1000
    assert_matches_evaluator(state, Evaluator(project), WEIGHTING)


def test_deshacer_restaura_exactamente() -> None:
    project = synthetic_project()
    model = build_model(project, project.timetables[0], WEIGHTING)
    state = State(model)
    rng = random.Random(5)
    construct(state, list(range(model.nsessions)), rng)
    antes = (state.cell[:], state.rooms[:], state.total, state.extra, state.violations())
    gen = MoveGenerator(state, rng)
    hechos = 0
    for _ in range(2000):
        cambios = gen.kinds[rng.randrange(len(gen.kinds))][1]()
        if cambios is None or state.apply(cambios) is None:
            continue
        state.undo()
        hechos += 1
    assert hechos > 50
    assert (state.cell, state.rooms, state.total, state.extra, state.violations()) == antes


# --------------------------------------------------------------------------- #
# Duras
# --------------------------------------------------------------------------- #


def _check_hard(project: UntisProject, result: HeuristicResult) -> None:
    tt = result.timetable
    rep = Evaluator(project).report(tt, WEIGHTING)
    assert hard_violations(rep.clashes) == []
    grids = project.grid_by_id
    lecciones = project.lesson_by_number
    ref = project.timetables[0]
    ref_celdas = {(a.lesson_number, a.day, a.period) for a in ref.assignments}
    duraciones = all_session_durations(project, ref)
    por_leccion = tt.by_lesson()
    for numero, asignaciones in por_leccion.items():
        le = lecciones[numero]
        assert not le.ignore
        grid = grids[le.time_grid]
        celdas = sorted({a.slot for a in asignaciones})
        # Todas las líneas del acople van en las mismas celdas.
        for i in range(len(le.lines)):
            assert sorted(a.slot for a in asignaciones if a.line == i) == celdas
        disponibles = list(duraciones[numero])
        for d, p in celdas:
            periodo = grid.period(p)
            assert periodo is not None
            if not periodo.is_teaching:
                # Solo una obligación puede quedarse en su recreo de referencia.
                assert (numero, d, p) in ref_celdas
                assert not any(line.classes or line.student_group for line in le.lines)
            assert periodo.duration in disponibles
            disponibles.remove(periodo.duration)
        if le.fixed:
            assert {(numero, d, p) for d, p in celdas} <= ref_celdas
    # Las lecciones fijadas conservan su celda.
    assert por_leccion[13][0].slot == (4, 1)


@pytest.mark.parametrize("strategy", [Strategy.A, Strategy.B, Strategy.D, Strategy.REPAIR])
def test_duras_y_evaluacion_del_resultado(strategy: Strategy) -> None:
    project = synthetic_project()
    result = optimize(project, strategy=strategy, weighting=WEIGHTING, time_limit=1.5)
    _check_hard(project, result)
    assert result.evaluation == Evaluator(project).evaluate(result.timetable, WEIGHTING)
    assert result.timetable.evaluation == result.evaluation
    sin = {(n, i) for n, i in result.unplaced}
    assert len(sin) == result.evaluation.unplaced_periods
    assert result.history
    assert result.elapsed < 5


def test_estrategia_d_deja_la_parte_facil_sin_colocar() -> None:
    project = synthetic_project()
    result = optimize(
        project, strategy=Strategy.D, placement_share=0.5, weighting=WEIGHTING, time_limit=1.0
    )
    lecciones = project.lesson_by_number
    lectivas = sum(le.periods_per_week for le in project.active_lessons if le.lines[0].classes)
    assert result.evaluation.unplaced_periods >= lectivas // 3
    # Las obligaciones (sin alumnos) siempre las coloca la heurística.
    assert all(
        lecciones[n].lines[0].classes or lecciones[n].lines[0].student_group
        for n, _ in result.unplaced
    )


# --------------------------------------------------------------------------- #
# Determinismo, parada y progreso
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("strategy", [Strategy.A, Strategy.B])
def test_determinista_con_semilla_e_iteraciones(strategy: Strategy) -> None:
    project = synthetic_project()

    def correr(seed: int) -> Timetable:
        return optimize(
            project,
            strategy=strategy,
            weighting=WEIGHTING,
            seed=seed,
            time_limit=120,
            max_iterations=4000,
        ).timetable

    a = correr(3)
    assert a.assignments == correr(3).assignments
    assert a.assignments != correr(4).assignments or len(a.assignments) < 10


def test_should_stop_se_respeta_y_hay_progreso() -> None:
    project = synthetic_project()
    avisos: list[str] = []
    inicio = time.perf_counter()

    def parar() -> bool:
        return time.perf_counter() - inicio > 0.3

    result = optimize(
        project,
        strategy=Strategy.E,
        weighting=WEIGHTING,
        time_limit=600,
        should_stop=parar,
        on_progress=lambda p: avisos.append(p.phase),
    )
    assert time.perf_counter() - inicio < 2.0
    assert result.evaluation == Evaluator(project).evaluate(result.timetable, WEIGHTING)
    assert "placement" in avisos
    assert set(avisos) <= {"placement", "improvement", "restart"}
