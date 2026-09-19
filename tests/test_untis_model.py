"""Pruebas del modelo de dominio Untis (`untis_model`).

Cubren las invariantes de cada entidad, la codificación de acoples en el id de
lección, la doble escala (deseos -3..+3, ponderaciones 0-5) y el diagnóstico de
datos de entrada.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scheduling_platform.untis_model import (
    LINES_PER_LESSON,
    SLIDER_WEIGHTS,
    TAB_OF_CRITERION,
    UNPLACED_PENALTY,
    UNSET,
    Absence,
    Assignment,
    CriterionScore,
    DateScheme,
    EntityKind,
    Evaluation,
    Holiday,
    Lesson,
    LessonLine,
    MinMax,
    PeriodDef,
    PeriodKind,
    Room,
    SchoolClass,
    SchoolInfo,
    Severity,
    StudentGroup,
    Subject,
    Substitution,
    SubstitutionKind,
    Supervision,
    SupervisionArea,
    Teacher,
    TimeGrid,
    TimeRequest,
    Timetable,
    UnspecifiedKind,
    UnspecifiedRequest,
    UntisProject,
    Weighting,
    WeightingTab,
    build_lesson_id,
    diagnose_data,
    double_periods_from_block,
    format_date,
    hhmm_to_minutes,
    minutes_to_hhmm,
    parse_date,
    slider_to_weight,
    split_lesson_id,
    weekday_of,
)

# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _grid(gid: str = "G", periods: int = 6, days: tuple[int, ...] = (1, 2, 3, 4, 5)) -> TimeGrid:
    defs = tuple(
        PeriodDef(number=n, start=420 + (n - 1) * 50, end=420 + (n - 1) * 50 + 45)
        for n in range(1, periods + 1)
    )
    return TimeGrid(id=gid, name=gid, days=days, periods=defs)


def _project(**cambios: object) -> UntisProject:
    base: dict[str, object] = {
        "time_grids": (_grid(),),
        "classes": (SchoolClass(id="5A", time_grid="G"),),
        "teachers": (Teacher(id="ANA"),),
        "rooms": (Room(id="R1"),),
        "subjects": (Subject(id="MAT"),),
        "lessons": (
            Lesson(
                number=1,
                lines=(LessonLine(subject="MAT", teacher="ANA", classes=("5A",)),),
                periods_per_week=4,
                time_grid="G",
            ),
        ),
    }
    base.update(cambios)
    return UntisProject(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# common: MinMax
# --------------------------------------------------------------------------- #


def test_minmax_por_defecto_no_restringe() -> None:
    assert not UNSET.is_set
    assert UNSET.contains(0)
    assert UNSET.contains(10_000)


def test_minmax_contains_respeta_ambos_extremos() -> None:
    r = MinMax(2, 4)
    assert r.is_set
    assert [r.contains(v) for v in range(6)] == [False, False, True, True, True, False]


@pytest.mark.parametrize(("lo", "hi"), [(-1, None), (None, -1), (5, 2)])
def test_minmax_rechaza_rangos_invalidos(lo: int | None, hi: int | None) -> None:
    with pytest.raises(ValueError):
        MinMax(lo, hi)


# --------------------------------------------------------------------------- #
# time_grid
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("texto", "minutos"), [("0700", 420), ("0935", 575), ("730", 450), ("2359", 1439)]
)
def test_hhmm_ida_y_vuelta(texto: str, minutos: int) -> None:
    assert hhmm_to_minutes(texto) == minutos
    assert hhmm_to_minutes(minutes_to_hhmm(minutos)) == minutos


@pytest.mark.parametrize("malo", ["", "7", "abcd", "2460", "12345"])
def test_hhmm_rechaza_basura(malo: str) -> None:
    with pytest.raises(ValueError):
        hhmm_to_minutes(malo)


def test_periodo_invariantes() -> None:
    p = PeriodDef(number=1, start=420, end=465)
    assert p.duration == 45
    assert p.is_teaching
    assert not PeriodDef(number=2, start=465, end=480, kind=PeriodKind.BREAK).is_teaching
    with pytest.raises(ValueError):
        PeriodDef(number=0, start=420, end=465)
    with pytest.raises(ValueError):
        PeriodDef(number=1, start=465, end=465)


def test_rejilla_slots_omite_recreos() -> None:
    g = TimeGrid(
        id="G",
        days=(1, 2),
        periods=(
            PeriodDef(1, 420, 465),
            PeriodDef(2, 465, 480, kind=PeriodKind.BREAK),
            PeriodDef(3, 480, 525),
        ),
    )
    assert g.slots() == ((1, 1), (1, 3), (2, 1), (2, 3))
    assert g.period(2) is not None
    assert g.period(9) is None
    assert g.display_name == "G"


def test_rejilla_rechaza_duplicados() -> None:
    with pytest.raises(ValueError):
        TimeGrid(id="G", days=(1, 1))
    with pytest.raises(ValueError):
        TimeGrid(id="G", periods=(PeriodDef(1, 420, 465), PeriodDef(1, 470, 515)))
    with pytest.raises(ValueError):
        TimeGrid(id="")


# --------------------------------------------------------------------------- #
# lessons: acoples explícitos en el id
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [
        ("LS_400", (4, 0)),
        ("LS_401", (4, 1)),
        ("LS_1009", (10, 9)),
        ("LS_7", (0, 7)),
        ("LS_134544", (1345, 44)),
    ],
)
def test_split_lesson_id(raw: str, esperado: tuple[int, int]) -> None:
    assert split_lesson_id(raw) == esperado


@given(st.integers(0, 10**6), st.integers(0, LINES_PER_LESSON - 1))
def test_lesson_id_ida_y_vuelta(numero: int, linea: int) -> None:
    assert split_lesson_id(build_lesson_id(numero, linea)) == (numero, linea)


def test_lesson_id_rechaza_linea_fuera_de_rango() -> None:
    with pytest.raises(ValueError):
        build_lesson_id(1, LINES_PER_LESSON)
    with pytest.raises(ValueError):
        split_lesson_id("LS_abc")


def test_leccion_acoplada_agrega_lineas() -> None:
    le = Lesson(
        number=40,
        lines=(
            LessonLine(subject="MAT", teacher="ANA", classes=("5A",), student_group="SG1"),
            LessonLine(subject="MAT", teacher="BEA", classes=("5A",), student_group="SG1"),
            LessonLine(subject="ING", teacher=None, classes=("5B",)),
        ),
        periods_per_week=5,
    )
    assert le.is_coupled
    assert le.id == "LS_4000"
    assert le.line_id(2) == "LS_4002"
    assert le.subjects == ("MAT", "ING")
    assert le.teachers == ("ANA", "BEA")
    assert le.classes == ("5A", "5B")
    assert le.student_groups == ("SG1",)
    assert le.lines[2].needs_teacher_optimization
    with pytest.raises(IndexError):
        le.line_id(3)


def test_leccion_invariantes() -> None:
    linea = LessonLine(subject="MAT")
    with pytest.raises(ValueError):
        Lesson(number=1, lines=(), periods_per_week=2)
    with pytest.raises(ValueError):
        Lesson(number=1, lines=(linea,) * (LINES_PER_LESSON + 1), periods_per_week=2)
    with pytest.raises(ValueError):
        Lesson(number=1, lines=(linea,), periods_per_week=-1)
    with pytest.raises(ValueError):
        Lesson(number=1, lines=(linea,), periods_per_week=2, block=(0,))
    with pytest.raises(ValueError):
        LessonLine(subject="")
    with pytest.raises(ValueError):
        LessonLine(subject="MAT", classes=("5A", "5A"))


def test_block_no_exige_sumar_los_periodos() -> None:
    """Regresión: `block="2,2"` con 2 períodos existe 77 veces en el export real."""
    le = Lesson(number=1, lines=(LessonLine(subject="MAT"),), periods_per_week=2, block=(2, 2))
    assert le.block == (2, 2)


@pytest.mark.parametrize(
    ("block", "periodos", "esperado"),
    [
        ((2, 2), 2, MinMax(1, 1)),  # un único doble
        ((2, 2), 4, MinMax(2, 2)),  # todo en dobles
        ((2,), 5, MinMax(1, 2)),  # al menos un doble
        ((2,), 6, MinMax(1, 3)),
        ((), 5, UNSET),
        ((2,), 1, UNSET),  # no cabe un doble
        ((3,), 6, UNSET),  # longitud no observada: sin exigencia de dobles
    ],
)
def test_dobles_desde_block(block: tuple[int, ...], periodos: int, esperado: MinMax) -> None:
    assert double_periods_from_block(block, periodos) == esperado


# --------------------------------------------------------------------------- #
# requests: escala -3..+3
# --------------------------------------------------------------------------- #


def test_deseo_duros_y_blandos() -> None:
    bloqueo = TimeRequest(EntityKind.TEACHER, "ANA", -3, day=1, period=2)
    obligatorio = TimeRequest(EntityKind.TEACHER, "ANA", 3, day=1, period=3)
    blando = TimeRequest(EntityKind.TEACHER, "ANA", -1, day=2)
    assert bloqueo.is_hard and bloqueo.is_block and not bloqueo.is_mandatory
    # +3 es "muy deseable", blando (datos reales: 1.519 celdas +3 en un curso).
    assert obligatorio.is_mandatory and not obligatorio.is_hard
    assert not blando.is_hard


def test_deseo_covers() -> None:
    celda = TimeRequest(EntityKind.CLASS, "5A", -2, day=1, period=2)
    dia = TimeRequest(EntityKind.CLASS, "5A", -2, day=3)
    periodo = TimeRequest(EntityKind.CLASS, "5A", -2, period=6)
    assert celda.covers(1, 2) and not celda.covers(1, 3)
    assert dia.covers(3, 1) and dia.covers(3, 9) and not dia.covers(2, 1)
    assert periodo.covers(1, 6) and periodo.covers(5, 6) and not periodo.covers(1, 5)


@pytest.mark.parametrize("valor", [-4, 4])
def test_deseo_fuera_de_escala(valor: int) -> None:
    with pytest.raises(ValueError):
        TimeRequest(EntityKind.ROOM, "R1", valor, day=1, period=1)


def test_deseo_necesita_dia_o_periodo() -> None:
    with pytest.raises(ValueError):
        TimeRequest(EntityKind.ROOM, "R1", -1)


def test_deseo_no_especificado() -> None:
    r = UnspecifiedRequest(EntityKind.TEACHER, "ANA", UnspecifiedKind.FREE_AFTERNOON, 2)
    assert r.count == 2
    with pytest.raises(ValueError):
        UnspecifiedRequest(EntityKind.TEACHER, "ANA", UnspecifiedKind.FREE_DAY, 0)


# --------------------------------------------------------------------------- #
# weighting: escala 0..5 no lineal
# --------------------------------------------------------------------------- #


def test_escala_no_lineal() -> None:
    assert [slider_to_weight(s) for s in range(6)] == list(SLIDER_WEIGHTS)
    # Untis advierte: el salto de 4 a 5 es enorme.
    assert slider_to_weight(5) >= 10 * slider_to_weight(4)
    with pytest.raises(ValueError):
        slider_to_weight(6)


def test_ponderacion_por_defecto_es_valida_y_completa() -> None:
    w = Weighting()
    criterios = Weighting.criteria()
    assert set(criterios) == set(TAB_OF_CRITERION)
    # Cada pestaña, salvo Análisis (solo lectura), tiene al menos un deslizador.
    pestanas = set(TAB_OF_CRITERION.values())
    assert pestanas == set(WeightingTab) - {WeightingTab.ANALYSIS}
    # Untis: como mucho un criterio en 5 y pocos en 4.
    valores = w.as_dict().values()
    assert sum(1 for v in valores if v == 5) <= 1
    assert w.weight("class_gaps") == slider_to_weight(w.class_gaps)


def test_ponderacion_rechaza_fuera_de_rango() -> None:
    with pytest.raises(ValueError):
        Weighting(teacher_gaps=6)
    with pytest.raises(KeyError):
        Weighting().weight("no_existe")


def test_ponderacion_from_dict_ignora_desconocidos() -> None:
    w = Weighting.from_dict({"teacher_gaps": 1, "criterio_futuro": 3})
    assert w.teacher_gaps == 1
    assert Weighting.from_dict(Weighting().as_dict()) == Weighting()


# --------------------------------------------------------------------------- #
# timetable: número de evaluación
# --------------------------------------------------------------------------- #


def test_evaluacion_no_colocados_dominan() -> None:
    blanda = Evaluation(scores=(CriterionScore("class_gaps", violations=1000, weight=300),))
    un_hueco = Evaluation(unplaced_periods=1)
    assert un_hueco.total == UNPLACED_PENALTY
    # Un período sin colocar pesa más que mil violaciones con el peso máximo.
    assert un_hueco.total < blanda.total or blanda.soft_points < UNPLACED_PENALTY * 10


def test_evaluacion_ordena_por_contribucion() -> None:
    e = Evaluation(
        scores=(
            CriterionScore("a", violations=1, weight=10),
            CriterionScore("b", violations=5, weight=30),
            CriterionScore("c", violations=0, weight=300),
        )
    )
    assert [s.criterion for s in e.by_contribution()] == ["b", "a", "c"]
    assert e.soft_points == 10 + 150


def test_horario_agrupa_por_leccion() -> None:
    tt = Timetable(
        id="v1",
        assignments=(
            Assignment(1, 0, 1, 1),
            Assignment(1, 0, 2, 1),
            Assignment(1, 1, 1, 1),
            Assignment(2, 0, 3, 4, room="R1"),
        ),
    )
    agrupado = tt.by_lesson()
    assert len(agrupado[1]) == 3
    assert tt.placed_periods(1, 0) == 2
    assert tt.placed_periods(1, 1) == 1
    assert agrupado[2][0].slot == (3, 4)
    with pytest.raises(ValueError):
        Assignment(1, 0, 0, 1)
    with pytest.raises(ValueError):
        Timetable(id="")


# --------------------------------------------------------------------------- #
# master_data
# --------------------------------------------------------------------------- #


def test_datos_maestros_invariantes() -> None:
    with pytest.raises(ValueError):
        Room(id="R1", room_weight=5)
    with pytest.raises(ValueError):
        Room(id="R1", alternative_room="R1")
    with pytest.raises(ValueError):
        Teacher(id="ANA", consecutive_max=0)
    with pytest.raises(ValueError):
        SchoolClass(id="5A", students=-1)
    with pytest.raises(ValueError):
        StudentGroup(id="SG", students=-1)
    assert Teacher(id="ANA", forename="Ana", surname="Ruiz").display_name == "Ana Ruiz"
    assert Teacher(id="ANA").display_name == "ANA"


# --------------------------------------------------------------------------- #
# project
# --------------------------------------------------------------------------- #


def test_proyecto_indices_y_consultas() -> None:
    p = _project()
    assert p.class_by_id["5A"].time_grid == "G"
    assert p.grid_for_class("5A") is not None
    assert p.grid_for_class("NO") is None
    assert [le.number for le in p.lessons_of_class("5A")] == [1]
    assert [le.number for le in p.lessons_of_teacher("ANA")] == [1]
    assert p.lesson_by_number[1].periods_per_week == 4


def test_proyecto_rechaza_ids_duplicados() -> None:
    p = _project(teachers=(Teacher(id="ANA"), Teacher(id="ANA")))
    with pytest.raises(ValueError):
        _ = p.teacher_by_id


def test_rejilla_rechaza_dias_menores_que_uno() -> None:
    with pytest.raises(ValueError, match="empiezan en 1"):
        TimeGrid(id="G", days=(0, 1, 2))
    with pytest.raises(ValueError, match="empiezan en 1"):
        TimeGrid(id="G", days=(-1,))


def test_proyecto_rechaza_horarios_con_id_repetido() -> None:
    with pytest.raises(ValueError, match="horario duplicado"):
        UntisProject(timetables=(Timetable(id="v1"), Timetable(id="v1", name="otra")))
    assert len(UntisProject(timetables=(Timetable(id="v1"), Timetable(id="v2"))).timetables) == 2


def test_campos_nuevos_con_valor_neutro() -> None:
    """Los campos añadidos van al final y por defecto vacíos: no rompen nada."""
    assert SchoolClass(id="C").text == ""
    profe = Teacher(id="T")
    assert (profe.text, profe.status, profe.payroll_number, profe.gender) == ("", "", "", "")
    assert Room(id="R").text == ""
    assert (Subject(id="S").fore_color, Subject(id="S").back_color) == ("", "")
    info = SchoolInfo()
    assert (info.school_type, info.term_begin, info.term_end) == ("", "", "")
    le = Lesson(1, (LessonLine("M"),), 1)
    assert (le.effective_begin, le.effective_end, le.occurrence) == ("", "", "")
    assert UntisProject().date_schemes == ()


def test_esquema_de_fechas() -> None:
    ds = DateScheme(id=".", pattern="11111FF", periodic_weeks="1")
    assert ds.display_name == "."
    p = UntisProject(date_schemes=(ds,))
    assert p.date_scheme_by_id == {".": ds}
    with pytest.raises(ValueError):
        DateScheme(id="")
    with pytest.raises(ValueError, match="duplicado"):
        _ = UntisProject(date_schemes=(ds, ds)).date_scheme_by_id


def test_proyecto_mutacion_funcional() -> None:
    p = _project()
    w = Weighting(teacher_gaps=1)
    assert p.with_weighting(w).weighting.teacher_gaps == 1
    assert p.weighting == Weighting()  # el original no cambia
    tt = Timetable(id="v1")
    p2 = p.with_timetable(tt).with_timetable(Timetable(id="v1", name="otra"))
    assert len(p2.timetables) == 1
    assert p2.timetable_by_id("v1") == Timetable(id="v1", name="otra")


def test_proyecto_lecciones_activas_excluyen_ignoradas() -> None:
    ignorada = Lesson(number=2, lines=(LessonLine(subject="MAT"),), periods_per_week=1, ignore=True)
    p = _project(lessons=(*_project().lessons, ignorada))
    assert [le.number for le in p.active_lessons] == [1]


def test_proyecto_deseos_por_entidad() -> None:
    r = TimeRequest(EntityKind.TEACHER, "ANA", -3, day=1, period=1)
    otro = TimeRequest(EntityKind.CLASS, "ANA", -3, day=1, period=1)
    p = _project(time_requests=(r, otro))
    assert p.requests_for(EntityKind.TEACHER, "ANA") == (r,)


# --------------------------------------------------------------------------- #
# diagnostics
# --------------------------------------------------------------------------- #


def test_diagnostico_proyecto_sano_sin_errores() -> None:
    assert [i for i in diagnose_data(_project()) if i.is_error] == []


def test_diagnostico_detecta_referencias_rotas() -> None:
    mala = Lesson(
        number=9,
        lines=(LessonLine(subject="NOPE", teacher="NADIE", classes=("ZZ",), room="R9"),),
        periods_per_week=2,
        time_grid="G",
    )
    codigos = {i.code for i in diagnose_data(_project(lessons=(mala,)))}
    assert {
        "linea_materia_inexistente",
        "linea_profesor_inexistente",
        "linea_clase_inexistente",
        "linea_aula_inexistente",
    } <= codigos


def test_diagnostico_clase_sobrecargada() -> None:
    enorme = Lesson(
        number=1,
        lines=(LessonLine(subject="MAT", teacher="ANA", classes=("5A",)),),
        periods_per_week=31,  # rejilla de 5 días x 6 períodos = 30
        time_grid="G",
    )
    issues = diagnose_data(_project(lessons=(enorme,)))
    assert any(i.code == "clase_sobrecargada" and i.entity_id == "5A" for i in issues)


def test_diagnostico_dobles_imposibles() -> None:
    le = Lesson(
        number=1,
        lines=(LessonLine(subject="MAT", teacher="ANA", classes=("5A",)),),
        periods_per_week=3,
        double_periods=MinMax(2, 2),
    )
    assert any(i.code == "dobles_imposibles" for i in diagnose_data(_project(lessons=(le,))))


def test_diagnostico_cadena_de_aulas() -> None:
    ciclo = (Room(id="A", alternative_room="B"), Room(id="B", alternative_room="A"))
    rota = (Room(id="C", alternative_room="NO"),)
    codigos = {i.code for i in diagnose_data(_project(rooms=(*ciclo, *rota)))}
    assert "aula_cadena_ciclica" in codigos
    assert "aula_alternativa_inexistente" in codigos


def test_diagnostico_deseos_contradictorios() -> None:
    reqs = (
        TimeRequest(EntityKind.TEACHER, "ANA", -3, day=1, period=1),
        TimeRequest(EntityKind.TEACHER, "ANA", 3, day=1, period=1),
    )
    issues = diagnose_data(_project(time_requests=reqs))
    assert any(i.code == "deseo_contradictorio" for i in issues)


def test_diagnostico_errores_primero_y_lecciones_ignoradas() -> None:
    ignorada_rota = Lesson(
        number=5, lines=(LessonLine(subject="NOPE"),), periods_per_week=1, ignore=True
    )
    issues = diagnose_data(
        _project(
            lessons=(*_project().lessons, ignorada_rota),
            rooms=(Room(id="R1"), Room(id="C", alternative_room="NO")),
            classes=(SchoolClass(id="5A", time_grid="NOGRID"),),
        )
    )
    # La lección ignorada no se diagnostica.
    assert not any(i.lesson_number == 5 for i in issues)
    severidades = [i.severity for i in issues]
    assert severidades == sorted(severidades, key=lambda s: s is not Severity.ERROR)


# --------------------------------------------------------------------------- #
# Guardias de recreo
# --------------------------------------------------------------------------- #


def test_zona_y_turno_de_guardia_validan_sus_datos() -> None:
    zona = SupervisionArea("Patio", "Patio grande", weight=3)
    assert zona.display_name == "Patio grande"
    with pytest.raises(ValueError, match="id"):
        SupervisionArea("")
    with pytest.raises(ValueError, match="0-5"):
        SupervisionArea("Patio", weight=9)
    turno = Supervision("Patio", 2, 4, teacher="T1", minutes=20)
    assert turno.slot == (2, 4) and turno.key == ("Patio", 2, 4) and turno.assigned
    assert not Supervision("Patio", 2, 4).assigned
    with pytest.raises(ValueError, match="zona"):
        Supervision("", 1, 1)
    with pytest.raises(ValueError, match="Día"):
        Supervision("Patio", 0, 1)
    with pytest.raises(ValueError, match="Recreo"):
        Supervision("Patio", 1, 0)


def test_guardias_de_un_profesor() -> None:
    p = _project(
        supervision_areas=(SupervisionArea("Patio"),),
        supervisions=(
            Supervision("Patio", 1, 3, teacher="ANA"),
            Supervision("Patio", 2, 3, teacher="LUIS"),
        ),
    )
    assert [g.day for g in p.supervisions_of_teacher("ANA")] == [1]
    assert p.area_by_id["Patio"].display_name == "Patio"


def test_profesor_con_minutos_de_guardia_y_reserva_de_sustitucion() -> None:
    profe = Teacher("T1", supervision_max=90, substitution_lock=4)
    assert profe.supervision_max == 90 and profe.substitution_lock == 4
    with pytest.raises(ValueError, match="minutos de guardia"):
        Teacher("T1", supervision_max=-1)
    with pytest.raises(ValueError, match="0-9"):
        Teacher("T1", substitution_lock=10)


# --------------------------------------------------------------------------- #
# Calendario, ausencias y sustituciones
# --------------------------------------------------------------------------- #


def test_fechas_untis() -> None:
    assert parse_date("20260907").month == 9
    assert format_date(parse_date("20261231")) == "20261231"
    assert weekday_of("20260907") == 1  # lunes
    for malo in ("", "2026-09-07", "2026090", "20261332"):
        with pytest.raises(ValueError, match=r"Fecha|month|day"):
            parse_date(malo)


def test_festivo_cubre_su_tramo() -> None:
    puente = Holiday("PUENTE", "Puente", "20261012", "20261013")
    assert puente.covers("20261012") and puente.covers("20261013")
    assert not puente.covers("20261014")
    suelto = Holiday("DIA", begin="20261012")
    assert suelto.covers("20261012") and not suelto.covers("20261013")
    with pytest.raises(ValueError, match="termina"):
        Holiday("X", begin="20261013", end="20261012")


def test_ausencia_con_horas_solo_acota_el_primer_y_ultimo_dia() -> None:
    a = Absence("A1", EntityKind.TEACHER, "ANA", "20261005", "20261007", 3, 4)
    assert not a.covers("20261005", 2) and a.covers("20261005", 3)
    assert a.covers("20261006", 1) and a.covers("20261006", 8)  # día entero en medio
    assert a.covers("20261007", 4) and not a.covers("20261007", 5)
    assert not a.covers_day("20261008")
    with pytest.raises(ValueError, match="termina antes"):
        Absence("A2", EntityKind.TEACHER, "ANA", "20261007", "20261005")
    with pytest.raises(ValueError, match="primera hora"):
        Absence("A3", EntityKind.CLASS, "1A", "20261005", first_period=5, last_period=2)
    # De varios días sí vale: "del lunes a 5ª hasta el miércoles a 2ª".
    larga = Absence("A4", EntityKind.TEACHER, "ANA", "20261005", "20261007", 5, 2)
    assert larga.covers("20261005", 5) and not larga.covers("20261005", 4)
    assert larga.covers("20261007", 2) and not larga.covers("20261007", 3)


def test_sustitucion_cuenta_segun_su_tipo() -> None:
    def sustitucion(**extra: object) -> Substitution:
        return Substitution(id="S1", date="20261005", period=3, lesson_number=1345, **extra)  # type: ignore[arg-type]

    assert sustitucion(teacher="LUIS").counts == 1
    assert sustitucion(kind=SubstitutionKind.CANCELLED, teacher="LUIS").counts == 0
    assert sustitucion().counts == 0  # sin nadie que la asuma
    assert sustitucion().open
    assert not sustitucion(kind=SubstitutionKind.CANCELLED).open


def test_consultas_del_dia_en_el_proyecto() -> None:
    p = _project(
        holidays=(Holiday("F", begin="20261012"),),
        absences=(Absence("A1", EntityKind.TEACHER, "ANA", "20261005"),),
        substitutions=(Substitution("S1", "20261005", 3, 1),),
    )
    assert p.is_holiday("20261012") and not p.is_holiday("20261013")
    assert [a.id for a in p.absences_on("20261005")] == ["A1"]
    assert not p.absences_on("20261006")
    assert [s.id for s in p.substitutions_on("20261005")] == ["S1"]
    assert p.absence_by_id["A1"].entity_id == "ANA"
