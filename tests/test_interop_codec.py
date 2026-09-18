"""Codec `UntisProject` <-> JSON: ida y vuelta sin pérdida y decodificación tolerante.

Las estrategias de hypothesis generan proyectos **válidos** (respetan cada
`__post_init__`) y se reutilizan desde `test_interop_rsp.py`.
"""

from __future__ import annotations

import json
from dataclasses import fields

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from scheduling_platform.interop.codec import (
    PROJECT_SECTIONS,
    CodecError,
    JsonObject,
    date_scheme_from_dict,
    date_scheme_to_dict,
    department_from_dict,
    lesson_from_dict,
    lesson_line_from_dict,
    lesson_to_dict,
    period_from_dict,
    project_from_dict,
    project_to_dict,
    room_from_dict,
    room_to_dict,
    school_class_from_dict,
    school_class_to_dict,
    school_info_from_dict,
    school_info_to_dict,
    student_group_from_dict,
    subject_from_dict,
    subject_to_dict,
    teacher_from_dict,
    teacher_to_dict,
    term_from_dict,
    time_grid_from_dict,
    time_request_from_dict,
    timetable_from_dict,
    unspecified_request_from_dict,
    weighting_from_dict,
)
from scheduling_platform.untis_model import (
    LINES_PER_LESSON,
    REQUEST_MAX,
    REQUEST_MIN,
    SLIDER_MAX,
    SLIDER_MIN,
    Assignment,
    CriterionScore,
    DateScheme,
    Department,
    EntityKind,
    Evaluation,
    HalfDay,
    Lesson,
    LessonLine,
    MinMax,
    PeriodDef,
    PeriodKind,
    Room,
    SchoolClass,
    SchoolInfo,
    StudentGroup,
    Subject,
    Teacher,
    Term,
    TimeGrid,
    TimeRequest,
    Timetable,
    UnspecifiedKind,
    UnspecifiedRequest,
    UntisProject,
    Weighting,
)

# --------------------------------------------------------------------------- #
# Estrategias
# --------------------------------------------------------------------------- #

ids = st.text(min_size=1, max_size=8)
textos = st.text(max_size=12)
opt_ids = st.none() | ids
nonneg = st.integers(min_value=0, max_value=10_000)
opt_nonneg = st.none() | nonneg
numeros = st.floats(allow_nan=False, allow_infinity=False, width=64)


@st.composite
def minmaxes(draw: st.DrawFn) -> MinMax:
    a = draw(opt_nonneg)
    b = draw(opt_nonneg)
    if a is not None and b is not None and a > b:
        a, b = b, a
    return MinMax(a, b)


@st.composite
def periods(draw: st.DrawFn, number: int) -> PeriodDef:
    start = draw(st.integers(min_value=0, max_value=24 * 60 - 1))
    return PeriodDef(
        number=number,
        start=start,
        end=draw(st.integers(min_value=start + 1, max_value=start + 300)),
        kind=draw(st.sampled_from(PeriodKind)),
        half_day=draw(st.sampled_from(HalfDay)),
        name=draw(textos),
    )


@st.composite
def time_grids(draw: st.DrawFn) -> TimeGrid:
    numeros_periodo = draw(st.lists(st.integers(1, 20), unique=True, max_size=6))
    return TimeGrid(
        id=draw(ids),
        name=draw(textos),
        days=tuple(draw(st.lists(st.integers(1, 7), min_size=1, max_size=7, unique=True))),
        periods=tuple(draw(periods(n)) for n in numeros_periodo),
    )


departments = st.builds(Department, id=ids, name=textos)

school_classes = st.builds(
    SchoolClass,
    id=ids,
    name=textos,
    time_grid=textos,
    home_room=opt_ids,
    department=opt_ids,
    students=nonneg,
    level=st.none() | st.integers(-5, 20),
    periods_per_day=minmaxes(),
    lunch_break=minmaxes(),
    main_subjects_per_day=st.none() | st.integers(-3, 10),
    main_subjects_consecutive=st.none() | st.integers(-3, 10),
    text=textos,
)

teachers = st.builds(
    Teacher,
    id=ids,
    name=textos,
    surname=textos,
    forename=textos,
    email=textos,
    department=opt_ids,
    home_room=opt_ids,
    periods_per_day=minmaxes(),
    days_per_week_max=opt_nonneg,
    ntp_per_day=minmaxes(),
    ntp_per_week=minmaxes(),
    lunch_break=minmaxes(),
    consecutive_max=st.none() | st.integers(1, 12),
    text=textos,
    status=textos,
    payroll_number=textos,
    gender=textos,
)


@st.composite
def rooms(draw: st.DrawFn) -> Room:
    ident = draw(ids)
    return Room(
        id=ident,
        name=draw(textos),
        capacity=draw(opt_nonneg),
        alternative_room=draw(opt_ids.filter(lambda x: x != ident)),
        room_weight=draw(st.integers(0, 4)),
        department=draw(opt_ids),
        text=draw(textos),
    )


subjects = st.builds(
    Subject,
    id=ids,
    name=textos,
    main_subject=st.booleans(),
    not_same_day=st.booleans(),
    double_period_required=st.booleans(),
    required_room=opt_ids,
    subject_group=opt_ids,
    fore_color=textos,
    back_color=textos,
)

student_groups = st.builds(
    StudentGroup,
    id=ids,
    name=textos,
    subject=opt_ids,
    classes=st.lists(ids, max_size=4).map(tuple),
    students=nonneg,
)


@st.composite
def terms(draw: st.DrawFn) -> Term:
    a, b = draw(textos), draw(textos)
    begin, end = (a, b) if a <= b else (b, a)
    return Term(id=draw(ids), name=draw(textos), begin=begin, end=end, time_grid=draw(opt_ids))


lesson_lines = st.builds(
    LessonLine,
    subject=ids,
    teacher=opt_ids,
    classes=st.lists(ids, max_size=4, unique=True).map(tuple),
    student_group=opt_ids,
    room=opt_ids,
    alternative_room=opt_ids,
    weekly_value=numeros,
)

lessons = st.builds(
    Lesson,
    number=nonneg,
    lines=st.lists(lesson_lines, min_size=1, max_size=LINES_PER_LESSON).map(tuple),
    periods_per_week=st.integers(0, 40),
    time_grid=textos,
    double_periods=minmaxes(),
    block=st.lists(st.integers(1, 6), max_size=4).map(tuple),
    fixed=st.booleans(),
    ignore=st.booleans(),
    not_same_day=st.booleans(),
    sequence_after=opt_ids,
    weekly_value=numeros,
    term=opt_ids,
    lesson_group=opt_ids,
    effective_begin=textos,
    effective_end=textos,
    occurrence=textos,
)


@st.composite
def time_requests(draw: st.DrawFn) -> TimeRequest:
    day = draw(st.none() | st.integers(1, 7))
    period = draw(st.integers(1, 20) if day is None else st.none() | st.integers(1, 20))
    return TimeRequest(
        entity_kind=draw(st.sampled_from(EntityKind)),
        entity_id=draw(ids),
        value=draw(st.integers(REQUEST_MIN, REQUEST_MAX)),
        day=day,
        period=period,
    )


unspecified_requests = st.builds(
    UnspecifiedRequest,
    entity_kind=st.sampled_from(EntityKind),
    entity_id=ids,
    kind=st.sampled_from(UnspecifiedKind),
    count=st.integers(1, 5),
)

weightings = st.fixed_dictionaries(
    {c: st.integers(SLIDER_MIN, SLIDER_MAX) for c in Weighting.criteria()}
).map(Weighting.from_dict)

assignments = st.builds(
    Assignment,
    lesson_number=nonneg,
    line=st.integers(0, 9),
    day=st.integers(1, 7),
    period=st.integers(1, 20),
    room=opt_ids,
    fixed=st.booleans(),
    manual=st.booleans(),
)

evaluations = st.builds(
    Evaluation,
    unplaced_periods=nonneg,
    clashes=nonneg,
    scores=st.lists(
        st.builds(CriterionScore, criterion=ids, violations=nonneg, weight=nonneg), max_size=4
    ).map(tuple),
)

timetables = st.builds(
    Timetable,
    id=ids,
    name=textos,
    assignments=st.lists(assignments, max_size=6).map(tuple),
    evaluation=evaluations,
)

school_infos = st.builds(
    SchoolInfo,
    name=textos,
    school_year_begin=textos,
    school_year_end=textos,
    header1=textos,
    header2=textos,
    footer=textos,
    term_name=textos,
    school_type=textos,
    term_begin=textos,
    term_end=textos,
)

date_schemes = st.builds(DateScheme, id=ids, pattern=textos, periodic_weeks=textos)


def _tuples[T](
    strategy: st.SearchStrategy[T], max_size: int = 3
) -> st.SearchStrategy[tuple[T, ...]]:
    return st.lists(strategy, max_size=max_size).map(tuple)


untis_projects: st.SearchStrategy[UntisProject] = st.builds(
    UntisProject,
    school=school_infos,
    time_grids=_tuples(time_grids()),
    departments=_tuples(departments),
    classes=_tuples(school_classes),
    teachers=_tuples(teachers),
    rooms=_tuples(rooms()),
    subjects=_tuples(subjects),
    student_groups=_tuples(student_groups),
    terms=_tuples(terms()),
    lessons=_tuples(lessons),
    time_requests=_tuples(time_requests()),
    unspecified_requests=_tuples(unspecified_requests),
    weighting=weightings,
    # `UntisProject` rechaza ids de horario repetidos.
    timetables=st.lists(timetables, max_size=3, unique_by=lambda t: t.id).map(tuple),
    date_schemes=_tuples(date_schemes),
)

_SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])


# --------------------------------------------------------------------------- #
# Propiedades
# --------------------------------------------------------------------------- #


@_SETTINGS
@given(untis_projects)
def test_ida_y_vuelta_sin_perdida(project: UntisProject) -> None:
    assert project_from_dict(project_to_dict(project)) == project


@_SETTINGS
@given(untis_projects)
def test_el_dict_es_json_y_sobrevive_al_texto(project: UntisProject) -> None:
    texto = json.dumps(project_to_dict(project), ensure_ascii=False, allow_nan=False)
    assert project_from_dict(json.loads(texto)) == project


def test_proyecto_vacio() -> None:
    assert project_from_dict(project_to_dict(UntisProject())) == UntisProject()
    assert project_from_dict({}) == UntisProject()


# --------------------------------------------------------------------------- #
# Tolerancia
# --------------------------------------------------------------------------- #


def test_claves_desconocidas_se_ignoran() -> None:
    project = UntisProject(teachers=(Teacher("T1", name="Ana"),))
    doc = project_to_dict(project)
    doc["futuro"] = {"algo": [1, 2, 3]}
    profes = doc["teachers"]
    assert isinstance(profes, list)
    primero = profes[0]
    assert isinstance(primero, dict)
    primero["campo_nuevo"] = True
    pond = doc["weighting"]
    assert isinstance(pond, dict)
    pond["criterio_futuro"] = 5
    assert project_from_dict(doc) == project


def test_claves_ausentes_toman_el_valor_por_defecto() -> None:
    """Un documento mínimo decodifica a la dataclass con sus valores por defecto.

    Protege contra divergencias entre los defaults del codec y los del modelo.
    """
    casos: list[tuple[object, object]] = [
        (department_from_dict({"id": "D"}), Department("D")),
        (school_class_from_dict({"id": "C"}), SchoolClass("C")),
        (teacher_from_dict({"id": "T"}), Teacher("T")),
        (room_from_dict({"id": "R"}), Room("R")),
        (subject_from_dict({"id": "S"}), Subject("S")),
        (student_group_from_dict({"id": "G"}), StudentGroup("G")),
        (term_from_dict({"id": "P"}), Term("P")),
        (school_info_from_dict({}), SchoolInfo()),
        (time_grid_from_dict({"id": "G"}), TimeGrid("G")),
        (period_from_dict({"number": 1, "start": 0, "end": 5}), PeriodDef(1, 0, 5)),
        (lesson_line_from_dict({"subject": "M"}), LessonLine("M")),
        (
            lesson_from_dict({"number": 1, "lines": [{"subject": "M"}], "periods_per_week": 2}),
            Lesson(1, (LessonLine("M"),), 2),
        ),
        (
            time_request_from_dict(
                {"entity_kind": "teacher", "entity_id": "T", "value": -3, "day": 1}
            ),
            TimeRequest(EntityKind.TEACHER, "T", -3, day=1),
        ),
        (
            unspecified_request_from_dict(
                {"entity_kind": "class", "entity_id": "C", "kind": "free_day"}
            ),
            UnspecifiedRequest(EntityKind.CLASS, "C", UnspecifiedKind.FREE_DAY),
        ),
        (weighting_from_dict({}), Weighting()),
        (timetable_from_dict({"id": "V1"}), Timetable("V1")),
        (date_scheme_from_dict({"id": "U"}), DateScheme("U")),
    ]
    for obtenido, esperado in casos:
        assert obtenido == esperado


def test_ponderacion_parcial_conserva_el_resto() -> None:
    w = weighting_from_dict({"teacher_gaps": 0, "desconocido": 9})
    assert w == Weighting(teacher_gaps=0)


# --------------------------------------------------------------------------- #
# Errores
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "doc",
    [
        {"id": "T", "days_per_week_max": "3"},
        {"id": "T", "days_per_week_max": True},
        {"id": 7},
        {"name": "sin id"},
        {"id": "T", "periods_per_day": [1, 2]},
        {"id": "T", "periods_per_day": {"min": 1.5}},
    ],
)
def test_tipos_incorrectos_fallan_con_codec_error(doc: JsonObject) -> None:
    with pytest.raises(CodecError):
        teacher_from_dict(doc)


def test_enum_desconocido_falla() -> None:
    with pytest.raises(CodecError, match="entity_kind"):
        time_request_from_dict({"entity_kind": "alien", "entity_id": "x", "value": 0, "day": 1})


def test_invariantes_del_modelo_siguen_vigentes() -> None:
    # El codec no esquiva los `__post_init__`: un MinMax invertido sigue fallando.
    with pytest.raises(ValueError, match="inconsistente"):
        teacher_from_dict({"id": "T", "periods_per_day": {"min": 5, "max": 2}})


def test_el_dict_emite_todos_los_campos() -> None:
    doc = teacher_to_dict(Teacher("T"))
    assert doc["periods_per_day"] == {"min": None, "max": None}
    assert doc["consecutive_max"] is None
    assert set(doc) == set(Teacher.__dataclass_fields__)


type _Entidad = SchoolClass | Room | Subject | SchoolInfo | Lesson | DateScheme


@pytest.mark.parametrize(
    ("doc", "entidad"),
    [
        (school_class_to_dict(SchoolClass("C")), SchoolClass("C")),
        (room_to_dict(Room("R")), Room("R")),
        (subject_to_dict(Subject("S")), Subject("S")),
        (school_info_to_dict(SchoolInfo()), SchoolInfo()),
        (lesson_to_dict(Lesson(1, (LessonLine("M"),), 1)), Lesson(1, (LessonLine("M"),), 1)),
        (date_scheme_to_dict(DateScheme("U")), DateScheme("U")),
    ],
)
def test_cada_entidad_emite_todos_sus_campos(doc: JsonObject, entidad: _Entidad) -> None:
    """Un campo nuevo del modelo que el codec olvide rompe aquí, no en producción."""
    assert set(doc) == {f.name for f in fields(entidad)}


def test_secciones_cubren_el_proyecto() -> None:
    assert set(PROJECT_SECTIONS) == {f.name for f in fields(UntisProject)}
    assert set(project_to_dict(UntisProject())) == set(PROJECT_SECTIONS)


def test_esquemas_de_fechas_ida_y_vuelta() -> None:
    project = UntisProject(date_schemes=(DateScheme(".", "11111FF", "1"),))
    doc = project_to_dict(project)
    assert doc["date_schemes"] == [{"id": ".", "pattern": "11111FF", "periodic_weeks": "1"}]
    assert project_from_dict(doc) == project
