"""Evaluador de referencia (`untis_model.evaluation`) y deducción de recreos.

El evaluador define qué significa cada deslizador. Se prueba criterio a
criterio con proyectos mínimos y, sobre el export real, que tres métodos
independientes —el evaluador, el `ValidationEngine` del motor y un barrido
directo del reloj de pared— vean exactamente los mismos choques.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scheduling_platform.bridge import timetable_to_solution, translate
from scheduling_platform.engine import ValidationEngine
from scheduling_platform.interop.xml import read_xml
from scheduling_platform.untis_model import (
    UNPLACED_PENALTY,
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
from scheduling_platform.untis_model.breaks import breaks_of, infer_breaks, used_periods
from scheduling_platform.untis_model.evaluation import CRITERIA, Evaluator, evaluate

# --------------------------------------------------------------------------- #
# Proyecto mínimo: 1 rejilla, 2 días, 6 períodos (el 4 es tarde)
# --------------------------------------------------------------------------- #


def _grid(breaks: tuple[int, ...] = ()) -> TimeGrid:
    periodos = tuple(
        PeriodDef(
            n,
            480 + (n - 1) * 50,
            480 + (n - 1) * 50 + 45,
            kind=PeriodKind.BREAK if n in breaks else PeriodKind.LESSON,
            half_day=HalfDay.AFTERNOON if n >= 4 else HalfDay.MORNING,
        )
        for n in range(1, 7)
    )
    return TimeGrid(id="G", days=(1, 2), periods=periodos)


def _lesson(
    n: int,
    subject: str = "MAT",
    teacher: str | None = "T1",
    *,
    per: int = 2,
    cls: tuple[str, ...] = ("C1",),
    room: str | None = None,
    **kw: object,
) -> Lesson:
    linea = LessonLine(subject=subject, teacher=teacher, classes=cls, room=room)
    return Lesson(number=n, lines=(linea,), periods_per_week=per, time_grid="G", **kw)  # type: ignore[arg-type]


def _project(
    lessons: tuple[Lesson, ...],
    cells: dict[int, list[tuple[int, int]]],
    rooms: dict[tuple[int, int, int], str] | None = None,
    **cambios: object,
) -> tuple[UntisProject, Timetable]:
    asign = tuple(
        Assignment(n, 0, d, p, room=(rooms or {}).get((n, d, p)))
        for n, celdas in cells.items()
        for d, p in celdas
    )
    tt = Timetable(id="t", assignments=asign)
    base: dict[str, object] = {
        "time_grids": (_grid(),),
        "classes": (
            SchoolClass(id="C1", time_grid="G", students=25),
            SchoolClass(id="C2", time_grid="G"),
        ),
        "teachers": (Teacher(id="T1"), Teacher(id="T2")),
        "rooms": (Room(id="R1", capacity=20, alternative_room="R2"), Room(id="R2"), Room(id="R3")),
        "subjects": (
            Subject(id="MAT", main_subject=True),
            Subject(id="ING", main_subject=True),
            Subject(id="ART"),
        ),
        "lessons": lessons,
        "timetables": (tt,),
    }
    base.update(cambios)
    return UntisProject(**base), tt  # type: ignore[arg-type]


def _viol(project: UntisProject, tt: Timetable, criterion: str) -> int:
    e = Evaluator(project).evaluate(tt)
    return next(s.violations for s in e.scores if s.criterion == criterion)


# --------------------------------------------------------------------------- #
# Estructura
# --------------------------------------------------------------------------- #


def test_cada_criterio_de_la_ponderacion_tiene_evaluador() -> None:
    assert set(CRITERIA) == set(Weighting.criteria())


def test_numero_de_evaluacion_suma_blandas_y_no_colocados() -> None:
    p, tt = _project((_lesson(1, per=3),), {1: [(1, 1)]})
    e = Evaluator(p).evaluate(tt)
    assert e.unplaced_periods == 2
    assert e.total == e.soft_points + 2 * UNPLACED_PENALTY


def test_ponderacion_cambia_pesos_no_violaciones() -> None:
    p, tt = _project((_lesson(1),), {1: [(1, 1), (1, 3)]})
    fuerte = evaluate(p, tt, Weighting(class_gaps=5))
    nada = evaluate(p, tt, Weighting(class_gaps=0))
    hueco = {s.criterion: s for s in fuerte.scores}["class_gaps"]
    assert hueco.violations == 1
    assert {s.criterion: s for s in nada.scores}["class_gaps"].points == 0
    assert fuerte.total > nada.total


def test_lecciones_ignoradas_no_cuentan() -> None:
    p, tt = _project((_lesson(1, ignore=True),), {1: [(1, 1), (1, 3)]})
    e = Evaluator(p).evaluate(tt)
    assert e.unplaced_periods == 0 and e.soft_points == 0


# --------------------------------------------------------------------------- #
# Duras
# --------------------------------------------------------------------------- #


def test_choque_de_profesor_entre_lecciones_distintas() -> None:
    p, tt = _project(
        (_lesson(1, per=1), _lesson(2, "ING", per=1, cls=("C2",))), {1: [(1, 1)], 2: [(1, 1)]}
    )
    rep = Evaluator(p).report(tt)
    assert [(c.kind, c.entity_id, c.lessons) for c in rep.clashes] == [("teacher", "T1", (1, 2))]


def test_obligaciones_no_lectivas_no_chocan() -> None:
    deber = _lesson(2, "ART", per=1, cls=())
    p, tt = _project((_lesson(1, per=1), deber), {1: [(1, 1)], 2: [(1, 1)]})
    assert Evaluator(p).report(tt).clashes == ()


def test_deseos_duros() -> None:
    reqs = (
        TimeRequest(EntityKind.TEACHER, "T1", -3, day=1, period=1),
        TimeRequest(EntityKind.CLASS, "C1", 3, day=2, period=2),
    )
    p, tt = _project((_lesson(1, per=1),), {1: [(1, 1)]}, time_requests=reqs)
    kinds = [c.kind for c in Evaluator(p).report(tt).clashes]
    assert kinds == ["time_request", "time_request"]  # -3 ocupado y +3 sin ocupar


# --------------------------------------------------------------------------- #
# Criterios blandos, uno a uno
# --------------------------------------------------------------------------- #


def test_huecos_de_clase_y_profesor() -> None:
    p, tt = _project((_lesson(1, per=2),), {1: [(1, 1), (1, 3)]})
    assert _viol(p, tt, "class_gaps") == 1
    assert _viol(p, tt, "teacher_gaps") == 1


def test_los_recreos_no_son_huecos() -> None:
    p, tt = _project((_lesson(1, per=2),), {1: [(1, 1), (1, 3)]}, time_grids=(_grid((2,)),))
    assert _viol(p, tt, "class_gaps") == 0


def test_periodos_por_dia_y_dias_por_semana() -> None:
    profe = Teacher(id="T1", periods_per_day=MinMax(None, 1), days_per_week_max=1)
    p, tt = _project(
        (_lesson(1, per=3),), {1: [(1, 1), (1, 2), (2, 1)]}, teachers=(profe, Teacher(id="T2"))
    )
    assert _viol(p, tt, "teacher_periods_per_day") == 1
    assert _viol(p, tt, "teacher_days_per_week_max") == 1


def test_periodos_seguidos_maximos() -> None:
    profe = Teacher(id="T1", consecutive_max=2)
    p, tt = _project(
        (_lesson(1, per=3),), {1: [(1, 1), (1, 2), (1, 3)]}, teachers=(profe, Teacher(id="T2"))
    )
    assert _viol(p, tt, "teacher_consecutive_max") == 1


def test_periodo_suelto_en_media_jornada_y_tarde_aislada() -> None:
    p, tt = _project((_lesson(1, per=2),), {1: [(1, 1), (1, 5)]})
    assert _viol(p, tt, "teacher_single_period_half_day") == 2  # mañana y tarde
    assert _viol(p, tt, "teacher_isolated_afternoon") == 1
    assert _viol(p, tt, "class_afternoon_periods") == 1


def test_almuerzo() -> None:
    profe = Teacher(id="T1", lunch_break=MinMax(1, None))
    # Franja de almuerzo = último período de mañana (3) y primero de tarde (4).
    p, tt = _project(
        (_lesson(1, per=4),),
        {1: [(1, 2), (1, 3), (1, 4), (1, 5)]},
        teachers=(profe, Teacher(id="T2")),
    )
    assert _viol(p, tt, "teacher_lunch_break") == 1


def test_dobles() -> None:
    le = _lesson(1, per=4, double_periods=MinMax(2, 2))
    bien, tt_bien = _project((le,), {1: [(1, 1), (1, 2), (2, 1), (2, 2)]})
    mal, tt_mal = _project((le,), {1: [(1, 1), (1, 3), (2, 1), (2, 2)]})
    assert _viol(bien, tt_bien, "subject_double_periods") == 0
    assert _viol(mal, tt_mal, "subject_double_periods") == 1


def test_no_mismo_dia_y_dias_seguidos() -> None:
    le = _lesson(1, per=2, not_same_day=True)
    p, tt = _project((le,), {1: [(1, 1), (1, 3)]})
    assert _viol(p, tt, "subject_not_same_day") == 1
    p2, tt2 = _project((le,), {1: [(1, 1), (2, 1)]})
    assert _viol(p2, tt2, "subject_not_consecutive_days") == 1


def test_secuencia_de_materias() -> None:
    antes = _lesson(1, "ING", "T2", per=1)
    despues = _lesson(2, "MAT", per=1, sequence_after="ING")
    p, tt = _project((antes, despues), {1: [(1, 3)], 2: [(1, 1)]})
    assert _viol(p, tt, "subject_sequence") == 1
    p2, tt2 = _project((antes, despues), {1: [(1, 1)], 2: [(1, 3)]})
    assert _viol(p2, tt2, "subject_sequence") == 0


def test_materias_principales() -> None:
    clase = SchoolClass(id="C1", time_grid="G", main_subjects_per_day=1)
    a = _lesson(1, "MAT", per=1)
    b = _lesson(2, "ING", "T2", per=1)
    p, tt = _project(
        (a, b), {1: [(1, 1)], 2: [(1, 2)]}, classes=(clase, SchoolClass(id="C2", time_grid="G"))
    )
    assert _viol(p, tt, "main_subject_per_day_max") == 1
    assert _viol(p, tt, "main_subject_not_consecutive") == 1
    tarde, tt3 = _project((a,), {1: [(1, 5)]})
    assert _viol(tarde, tt3, "main_subject_morning") == 1


def test_grupo_de_materias_seguidas() -> None:
    materias = (
        Subject(id="MAT", subject_group="CIEN"),
        Subject(id="ING", subject_group="CIEN"),
        Subject(id="ART"),
    )
    p, tt = _project(
        (_lesson(1, "MAT", per=1), _lesson(2, "ING", "T2", per=1)),
        {1: [(1, 1)], 2: [(1, 2)]},
        subjects=materias,
    )
    assert _viol(p, tt, "subject_group_not_consecutive") == 1


def test_aulas_cadena_capacidad_y_exigida() -> None:
    materias = (Subject(id="MAT", required_room="R1"), Subject(id="ING"), Subject(id="ART"))
    le = _lesson(1, "MAT", per=3, room="R1")
    p, tt = _project(
        (le,),
        {1: [(1, 1), (1, 2), (2, 1)]},
        rooms={(1, 1, 1): "R1", (1, 1, 2): "R2", (1, 2, 1): "R3"},
        subjects=materias,
    )
    assert _viol(p, tt, "room_alternative_chain") == 1  # R2 = alternativa nº 1
    assert _viol(p, tt, "room_optimization") == 1  # R3 no está en la cadena
    assert _viol(p, tt, "subject_required_room") == 2  # R2 y R3 no son R1
    assert _viol(p, tt, "room_capacity") == 1  # 25 alumnos en R1 (20)


def test_distribucion() -> None:
    le = _lesson(1, "MAT", per=3)
    p, tt = _project((le,), {1: [(1, 1), (1, 3), (2, 1)]})
    assert _viol(p, tt, "distribution_same_day") == 1  # dos tramos el día 1
    assert _viol(p, tt, "distribution_uniform_week") == 0  # usa 2 de 2 días
    assert _viol(p, tt, "distribution_same_period_consecutive_days") == 1  # p1 días 1 y 2
    ultimo, tt2 = _project((_lesson(1, per=1),), {1: [(1, 6)]})
    assert _viol(ultimo, tt2, "distribution_first_last_period") == 1


def test_deseos_blandos_y_no_especificados() -> None:
    reqs = (
        TimeRequest(EntityKind.TEACHER, "T1", -2, day=1, period=1),
        TimeRequest(EntityKind.CLASS, "C1", -1, day=1),
        TimeRequest(EntityKind.SUBJECT, "MAT", -1, period=1),
    )
    libre = (UnspecifiedRequest(EntityKind.TEACHER, "T1", UnspecifiedKind.FREE_DAY, 1),)
    p, tt = _project(
        (_lesson(1, per=2),), {1: [(1, 1), (2, 2)]}, time_requests=reqs, unspecified_requests=libre
    )
    assert _viol(p, tt, "time_request_teacher") == 2
    assert _viol(p, tt, "time_request_class") == 1
    assert _viol(p, tt, "time_request_subject") == 1
    assert _viol(p, tt, "time_request_unspecified") == 1  # trabaja los 2 días


def test_optimizacion_de_profesores_cuenta_lineas_sin_profesor() -> None:
    p, tt = _project((_lesson(1, teacher=None, per=1),), {1: [(1, 1)]})
    assert _viol(p, tt, "teacher_optimization") == 1


# --------------------------------------------------------------------------- #
# Recreos deducidos
# --------------------------------------------------------------------------- #


def test_infer_breaks_marca_solo_periodos_cortos_sin_clase() -> None:
    corto = (
        PeriodDef(1, 480, 525),
        PeriodDef(2, 525, 545),
        PeriodDef(3, 545, 590),
        PeriodDef(4, 590, 600),
    )
    g = TimeGrid(id="G", days=(1,), periods=corto)
    p, _ = _project((_lesson(1, per=2),), {1: [(1, 1), (1, 4)]}, time_grids=(g,))
    q = infer_breaks(p)
    # p2 (20 min) libre -> recreo; p4 (10 min) aloja una lección -> sigue lectivo.
    assert breaks_of(q) == {"G": (2,)}
    assert infer_breaks(q) == q  # idempotente


def test_infer_breaks_sin_horario_no_cambia_nada() -> None:
    p, _ = _project((_lesson(1),), {})
    sin = UntisProject(time_grids=p.time_grids, lessons=p.lessons, classes=p.classes)
    assert infer_breaks(sin) == sin


@settings(max_examples=40, deadline=None)
@given(
    st.lists(st.tuples(st.integers(1, 2), st.integers(1, 6)), min_size=1, max_size=8, unique=True)
)
def test_infer_breaks_nunca_marca_un_periodo_ocupado(celdas: list[tuple[int, int]]) -> None:
    periodos = tuple(
        PeriodDef(n, 480 + n * 50, 480 + n * 50 + (20 if n % 2 else 45)) for n in range(1, 7)
    )
    g = TimeGrid(id="G", days=(1, 2), periods=periodos)
    p, tt = _project((_lesson(1, per=len(celdas)),), {1: celdas}, time_grids=(g,))
    marcados = set(breaks_of(infer_breaks(p))["G"])
    assert not marcados & {pe for _, pe in used_periods(p, tt)}


# --------------------------------------------------------------------------- #
# Export real: tres métodos independientes coinciden
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def anon(anon_xml_path: Path) -> UntisProject:
    return infer_breaks(read_xml(anon_xml_path))


def test_real_recreos_deducidos(anon: UntisProject) -> None:
    recreos = breaks_of(anon)
    assert recreos["Bachillerato"] == (5,)
    assert recreos["Primaria"] == (4,)
    # El período 1 de Bachillerato (10 min, dirección de grupo) sigue lectivo.
    assert 1 not in recreos["Bachillerato"]


def test_real_evaluacion_del_horario_de_untis(anon: UntisProject) -> None:
    rep = Evaluator(anon).report(anon.timetables[0])
    e = rep.evaluation
    assert e.clashes == 7
    assert {c.kind for c in rep.clashes} == {"teacher"}
    assert e.unplaced_periods == 4  # L11390 (10/7) y L11470 (2/1), ambas obligaciones
    assert {s.criterion: s.violations for s in e.scores}["subject_double_periods"] == 1


def test_real_tres_metodos_ven_los_mismos_choques(anon: UntisProject) -> None:
    rep = Evaluator(anon).report(anon.timetables[0])
    evaluador = {(c.entity_id, c.lessons) for c in rep.clashes}

    tr = translate(anon)
    informe = ValidationEngine().validate(
        tr.problem, timetable_to_solution(tr, anon.timetables[0]).solution
    )
    nombre_de = {t.display_name: t.id for t in anon.teachers}
    patron = re.compile(r"El recurso '(?P<res>.+)' aloja")
    motor = {nombre_de[m["res"]] for i in informe.issues if (m := patron.match(i.message))}

    assert {profe for profe, _ in evaluador} == motor
    assert len(evaluador) == 7


def test_real_evaluacion_es_rapida_y_determinista(anon: UntisProject) -> None:
    ev = Evaluator(anon)
    a = ev.evaluate(anon.timetables[0])
    b = ev.evaluate(anon.timetables[0])
    assert a == b
