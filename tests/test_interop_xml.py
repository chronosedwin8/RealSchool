"""Pruebas de `interop.xml`: lectura y escritura del XmlInterface de Untis.

El export seudonimizado (`untis_anon.xml`) se parsea una sola vez por módulo;
la ida y vuelta XML -> modelo -> XML -> modelo es la prueba de aceptación.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from pathlib import Path

import pytest

from scheduling_platform.interop.gpu import write_gpu001
from scheduling_platform.interop.xml import (
    DROPPED_FIELDS,
    ID_PREFIXES,
    MISSING_SUBJECT_ID,
    REGENERATED_FIELDS,
    UNTIS_NS,
    UNTIS_TIMETABLE_ID,
    add_prefix,
    read_xml,
    split_refs,
    strip_prefix,
    write_xml,
)
from scheduling_platform.untis_model import (
    DateScheme,
    HalfDay,
    MinMax,
    PeriodKind,
    Severity,
    Timetable,
    UntisProject,
    diagnose_data,
)


@pytest.fixture(scope="module")
def anon(anon_xml_path: Path) -> UntisProject:
    return read_xml(anon_xml_path)


def _timetable(project: UntisProject) -> Timetable:
    tt = project.timetable_by_id(UNTIS_TIMETABLE_ID)
    assert tt is not None
    return tt


def _assert_projects_equal(a: UntisProject, b: UntisProject) -> None:
    """Compara campo a campo para que un fallo diga qué colección difiere."""
    for f in fields(UntisProject):
        assert getattr(a, f.name) == getattr(b, f.name), f"difiere {f.name}"
    assert a == b


# --------------------------------------------------------------------------- #
# Lectura del export seudonimizado
# --------------------------------------------------------------------------- #


def test_counts(anon: UntisProject) -> None:
    assert len(anon.classes) == 66
    assert len(anon.teachers) == 116
    assert len(anon.rooms) == 95
    # 278 materias del XML + la materia comodín de las 3 líneas sin materia.
    assert len([s for s in anon.subjects if s.id != MISSING_SUBJECT_ID]) == 278
    assert len(anon.subjects) == 279
    assert len(anon.time_grids) == 8
    assert len(anon.lessons) == 709
    assert len(anon.student_groups) == 109
    assert len(anon.departments) == 12


def test_couplings(anon: UntisProject) -> None:
    assert sum(le.is_coupled for le in anon.lessons) == 199
    # Acoples de más de 10 líneas: el id lleva la línea con dos cifras.
    assert max(len(le.lines) for le in anon.lessons) == 45
    assert sum(len(le.lines) for le in anon.lessons) == 1232


def test_timetable_assignments(anon: UntisProject) -> None:
    assert len(anon.timetables) == 1
    assert len(_timetable(anon).assignments) == 3020


def test_lesson_4_is_a_coupling(anon: UntisProject) -> None:
    le = anon.lesson_by_number[4]
    assert len(le.lines) == 2
    assert le.lines[0].teacher != le.lines[1].teacher
    assert le.lines[0].subject == le.lines[1].subject == "MATK1"
    assert le.lines[0].weekly_value == 5.0
    assert le.periods_per_week == 5
    por_linea = {
        i: sorted(
            a.slot for a in _timetable(anon).assignments if a.lesson_number == 4 and a.line == i
        )
        for i in (0, 1)
    }
    assert len(por_linea[0]) == 5
    assert por_linea[0] == por_linea[1]
    # El aula colocada solo viaja en la línea 0 del acople.
    rooms = {a.line: a.room for a in _timetable(anon).assignments if a.lesson_number == 4}
    assert rooms[0] is not None
    assert rooms[1] is None


def test_class_ids_with_spaces(anon: UntisProject) -> None:
    clases = anon.class_by_id
    assert "12-GIB 2" in clases
    usadas = {c for le in anon.lessons for c in le.classes}
    assert {"12-GIB 2", "12-GIB 3", "12-GIB 4"} <= usadas
    assert usadas <= set(clases)


def test_ids_are_untis_short_names(anon: UntisProject) -> None:
    """Contrato de ids: ninguna entidad ni referencia conserva el prefijo XML."""
    ids = [
        *(c.id for c in anon.classes),
        *(t.id for t in anon.teachers),
        *(r.id for r in anon.rooms),
        *(s.id for s in anon.subjects),
        *(d.id for d in anon.departments),
        *(g.id for g in anon.student_groups),
        *(ds.id for ds in anon.date_schemes),
    ]
    refs = [
        *(c.home_room for c in anon.classes if c.home_room),
        *(c.department for c in anon.classes if c.department),
        *(t.department for t in anon.teachers if t.department),
        *(r.department for r in anon.rooms if r.department),
        *(g.subject for g in anon.student_groups if g.subject),
        *(c for g in anon.student_groups for c in g.classes),
        *(ln.subject for le in anon.lessons for ln in le.lines),
        *(ln.teacher for le in anon.lessons for ln in le.lines if ln.teacher),
        *(c for le in anon.lessons for c in le.classes),
        *(g for le in anon.lessons for g in le.student_groups),
        *(a.room for a in _timetable(anon).assignments if a.room),
    ]
    # Solo se quita un prefijo: `SU_SU__K3` es la materia de nombre corto `SU__K3`.
    assert {i for i in ids + refs if i.startswith(ID_PREFIXES)} == {"SU__K3", "SU__K4"}
    assert {"K1A", "12-GIB 2"} <= set(anon.class_by_id)
    assert "T028" in anon.teacher_by_id
    assert "P 11" in anon.room_by_id
    assert "B" in anon.department_by_id
    assert "MATK1_K1A" in anon.student_group_by_id
    # Todas las referencias resuelven contra los datos maestros sin prefijo.
    assert {c for le in anon.lessons for c in le.classes} <= set(anon.class_by_id)
    assert {t for le in anon.lessons for t in le.teachers} <= set(anon.teacher_by_id)
    assert {s for le in anon.lessons for s in le.subjects} <= set(anon.subject_by_id)
    assert {a.room for a in _timetable(anon).assignments if a.room} <= set(anon.room_by_id)


def test_new_fields_from_real_export(anon: UntisProject) -> None:
    assert anon.school.term_begin == "20250714"
    assert anon.school.term_end == "20260630"
    assert anon.school.school_type == ""
    (esquema,) = anon.date_schemes
    assert esquema.id == "."
    assert len(esquema.pattern) == 352
    assert anon.date_scheme_by_id["."] == esquema
    con_color = [s for s in anon.subjects if s.back_color]
    assert len(con_color) == 162
    assert all(s.fore_color.startswith("#") for s in con_color)
    le = anon.lesson_by_number[4]
    assert (le.effective_begin, le.effective_end) == ("20250714", "20260630")
    assert le.occurrence == esquema.pattern


def test_gpu001_uses_short_names(anon: UntisProject, tmp_path: Path) -> None:
    """GPU001 (lo que consume MiUntisWeb) sale con nombres cortos, sin prefijos."""
    ruta = write_gpu001(anon, tmp_path / "GPU001.TXT")
    lineas = ruta.read_text(encoding="cp1252").splitlines()
    assert lineas[0].startswith('4,"K1A","T028","MATK1",')
    assert not [ln for ln in lineas if any(f'"{p}' in ln for p in ID_PREFIXES)]


def test_double_periods_from_block(anon: UntisProject) -> None:
    le = next(le for le in anon.lessons if le.block == (2, 2) and le.periods_per_week == 2)
    assert le.double_periods == MinMax(1, 1)
    # `block="2,2"` con solo 2 períodos: no suma los períodos, es un único doble.
    # 77 elementos `<lesson>` (líneas) del XML, agrupados en 34 lecciones.
    dobles = [x for x in anon.lessons if x.block == (2, 2) and x.periods_per_week == 2]
    assert len(dobles) == 34
    assert sum(len(x.lines) for x in dobles) == 77
    assert all(x.double_periods == MinMax(1, 1) for x in dobles)
    single = next(le for le in anon.lessons if le.block == (2,))
    assert single.double_periods == MinMax(1, single.periods_per_week // 2)


def test_time_grids(anon: UntisProject) -> None:
    for g in anon.time_grids:
        assert g.days == (1, 2, 3, 4, 5)
        assert len(g.periods) == 15
        assert all(p.kind is PeriodKind.LESSON for p in g.periods)
        for p in g.periods:
            esperado = HalfDay.AFTERNOON if p.start >= 12 * 60 else HalfDay.MORNING
            assert p.half_day is esperado
    clases = {c.time_grid for c in anon.classes}
    assert clases <= {g.id for g in anon.time_grids}


def test_missing_subject_and_teacher(anon: UntisProject) -> None:
    lineas = [ln for le in anon.lessons for ln in le.lines]
    assert sum(ln.subject == MISSING_SUBJECT_ID for ln in lineas) == 3
    assert sum(ln.teacher is None for ln in lineas) == 3


def test_diagnostics_have_no_errors(anon: UntisProject) -> None:
    issues = diagnose_data(anon)
    assert [i for i in issues if i.severity is Severity.ERROR] == []


# --------------------------------------------------------------------------- #
# Ida y vuelta
# --------------------------------------------------------------------------- #


def test_round_trip_anon(anon: UntisProject, tmp_path: Path) -> None:
    salida = tmp_path / "anon.xml"
    write_xml(anon, salida, now=datetime(2026, 3, 21, 10, 17, 2))
    texto = salida.read_text(encoding="utf-8")
    assert texto.startswith("<?xml version='1.0' encoding='utf-8'?>")
    assert f'<document xmlns="{UNTIS_NS}"' in texto
    assert 'date="20260321" time="101702"' in texto
    # Al escribir se reponen los prefijos de XmlInterface.
    assert '<class id="CL_12-GIB 2">' in texto
    assert '<lesson_teacher id="TR_T028" />' in texto
    assert '<lesson_date_scheme id="UG_.">' in texto
    _assert_projects_equal(anon, read_xml(salida))


def test_round_trip_real(real_xml_paths: list[Path], tmp_path: Path) -> None:
    for i, path in enumerate(real_xml_paths):
        original = read_xml(path)
        salida = tmp_path / f"real_{i}.xml"
        write_xml(original, salida)
        _assert_projects_equal(original, read_xml(salida))


# --------------------------------------------------------------------------- #
# XML sintético
# --------------------------------------------------------------------------- #

_SYNTHETIC = """<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="https://untis.at/untis/XmlInterface" version="3.1">
  <general>
    <schoolname>Escuela</schoolname>
    <schoolyearbegindate>20250901</schoolyearbegindate>
    <schoolyearenddate>20260630</schoolyearenddate>
    <header1>Cabecera</header1>
    <termname>Curso</termname>
    <termbegindate>20250901</termbegindate>
    <termenddate>20260131</termenddate>
    <schooltype>Colegio</schooltype>
  </general>
  <timeperiods>
    <timeperiod id="TP_1"><day>1</day><period>1</period><starttime>0800</starttime>
      <endtime>0845</endtime><timegrid>G</timegrid></timeperiod>
    <timeperiod id="TP_2"><day>1</day><period>2</period><starttime>1200</starttime>
      <endtime>1245</endtime><timegrid>G</timegrid></timeperiod>
    <timeperiod id="TP_3"><day>2</day><period>1</period><starttime>0800</starttime>
      <endtime>0845</endtime><timegrid>G</timegrid></timeperiod>
    <timeperiod id="TP_4"><day>2</day><period>2</period><starttime>1200</starttime>
      <endtime>1245</endtime><timegrid>G</timegrid></timeperiod>
  </timeperiods>
  <departments><department id="DP_A"><longname>Dep A</longname></department></departments>
  <rooms><room id="RM_1 A"><longname>Aula 1</longname><text>Planta 1</text>
    <room_department id="DP_A"/></room></rooms>
  <subjects>
    <subject id="SU_MAT"><longname>Mates</longname><forecolor>#000000</forecolor>
      <backcolor>16744448</backcolor></subject>
  </subjects>
  <teachers>
    <teacher id="TR_X"><forename>Ana</forename><surname>Pérez</surname><gender>F</gender>
      <status>Docente,</status><payrollnumber>123</payrollnumber>
      <email>a@x.org</email><text>Tutora</text><teacher_department id="DP_A"/></teacher>
    <teacher id="TR_Y"><surname>Ruiz</surname></teacher>
  </teachers>
  <classes>
    <class id="CL_1 A"><longname>Primero A</longname><text>Grupo bilingüe</text>
      <timegrid>G</timegrid><class_room id="RM_1 A"/><class_department id="DP_A"/></class>
    <class id="CL_1B"><timegrid>G</timegrid></class>
  </classes>
  <studentgroups>
    <studentgroup id="SG_MAT"><subject id="SU_MAT"/>
      <classes><class id="CL_1 A"/><class id="CL_1B"/></classes></studentgroup>
  </studentgroups>
  <lesson_date_schemes>
    <lesson_date_scheme id="UG_A"><date_scheme>11F11</date_scheme>
      <periodic_weeks>2</periodic_weeks></lesson_date_scheme>
  </lesson_date_schemes>
  <lessons>
    <lesson id="LS_700">
      <periods>2</periods><lesson_subject id="SU_MAT"/><lesson_teacher id="TR_X"/>
      <lesson_classes id="CL_1 A CL_1B"/><timegrid>G</timegrid>
      <teacher_value>250000</teacher_value><lesson_studentgroups id="SG_MAT"/>
      <effectivebegindate>20250901</effectivebegindate>
      <effectiveenddate>20251220</effectiveenddate>
      <block>2,2</block><occurence>11F11</occurence>
      <times>
        <time><assigned_day>1</assigned_day><assigned_period>1</assigned_period>
          <assigned_starttime>0800</assigned_starttime><assigned_endtime>0845</assigned_endtime>
          <assigned_room id="RM_1 A"/></time>
        <time><assigned_day>1</assigned_day><assigned_period>2</assigned_period>
          <assigned_starttime>1200</assigned_starttime><assigned_endtime>1245</assigned_endtime>
          <assigned_room id="RM_1 A"/></time>
      </times>
    </lesson>
    <lesson id="LS_701">
      <periods>2</periods><lesson_teacher id="TR_Y"/><timegrid>G</timegrid>
      <block>2,2</block>
      <times>
        <time><assigned_day>1</assigned_day><assigned_period>1</assigned_period></time>
        <time><assigned_day>1</assigned_day><assigned_period>2</assigned_period></time>
      </times>
    </lesson>
    <lesson id="LS_800">
      <periods>1</periods><lesson_subject id="SU_MAT"/><lesson_classes id="CL_1B"/>
      <timegrid>G</timegrid><times/>
    </lesson>
  </lessons>
</document>
"""


def test_synthetic(tmp_path: Path) -> None:
    fuente = tmp_path / "sintetico.xml"
    fuente.write_text(_SYNTHETIC, encoding="utf-8")
    p = read_xml(fuente)

    assert p.school.name == "Escuela"
    assert p.school.header1 == "Cabecera"
    assert p.school.term_name == "Curso"
    assert (p.school.school_type, p.school.term_begin, p.school.term_end) == (
        "Colegio",
        "20250901",
        "20260131",
    )
    assert p.date_schemes == (DateScheme(id="A", pattern="11F11", periodic_weeks="2"),)

    (grid,) = p.time_grids
    assert grid.id == "G"
    assert grid.days == (1, 2)
    assert [(q.number, q.start, q.end) for q in grid.periods] == [(1, 480, 525), (2, 720, 765)]
    assert [q.half_day for q in grid.periods] == [HalfDay.MORNING, HalfDay.AFTERNOON]

    clase = p.class_by_id["1 A"]
    assert (clase.name, clase.time_grid, clase.home_room, clase.department, clase.text) == (
        "Primero A",
        "G",
        "1 A",
        "A",
        "Grupo bilingüe",
    )
    profe = p.teacher_by_id["X"]
    assert (profe.forename, profe.surname, profe.email, profe.department) == (
        "Ana",
        "Pérez",
        "a@x.org",
        "A",
    )
    assert (profe.gender, profe.status, profe.payroll_number, profe.text) == (
        "F",
        "Docente,",
        "123",
        "Tutora",
    )
    aula = p.room_by_id["1 A"]
    assert (aula.department, aula.text) == ("A", "Planta 1")
    materia = p.subject_by_id["MAT"]
    assert (materia.name, materia.fore_color, materia.back_color) == (
        "Mates",
        "#000000",
        "16744448",
    )
    assert p.student_group_by_id["MAT"].classes == ("1 A", "1B")

    assert [le.number for le in p.lessons] == [7, 8]
    acople = p.lesson_by_number[7]
    assert len(acople.lines) == 2
    l0, l1 = acople.lines
    assert l0.classes == ("1 A", "1B")
    assert l0.weekly_value == 2.5
    assert l0.student_group == "MAT"
    assert l1.subject == MISSING_SUBJECT_ID
    assert l1.weekly_value == 0.0
    assert acople.block == (2, 2)
    assert acople.double_periods == MinMax(1, 1)
    assert (acople.effective_begin, acople.effective_end, acople.occurrence) == (
        "20250901",
        "20251220",
        "11F11",
    )
    assert p.lesson_by_number[8].lines[0].teacher is None
    assert MISSING_SUBJECT_ID in p.subject_by_id

    tt = _timetable(p)
    assert len(tt.assignments) == 4
    assert tt.placed_periods(7, 0) == 2
    assert tt.placed_periods(8, 0) == 0

    assert [i for i in diagnose_data(p) if i.is_error] == []

    salida = tmp_path / "salida.xml"
    write_xml(p, salida)
    texto = salida.read_text(encoding="utf-8")
    assert MISSING_SUBJECT_ID == "?"
    assert 'id="SU_?"' not in texto
    assert 'lesson_classes id="CL_1 A CL_1B"' in texto
    assert "<teacher_value>250000</teacher_value>" in texto
    assert "<assigned_starttime>1200</assigned_starttime>" in texto
    _assert_projects_equal(p, read_xml(salida))


def test_no_times_means_no_timetable(tmp_path: Path) -> None:
    fuente = tmp_path / "vacio.xml"
    fuente.write_text(
        '<document xmlns="https://untis.at/untis/XmlInterface">'
        "<lessons><lesson id='LS_100'><periods>1</periods>"
        "<lesson_subject id='SU_A'/><times/></lesson></lessons></document>",
        encoding="utf-8",
    )
    p = read_xml(fuente)
    assert p.timetables == ()
    assert len(p.lessons) == 1


def test_non_contiguous_lines_rejected(tmp_path: Path) -> None:
    fuente = tmp_path / "hueco.xml"
    fuente.write_text(
        '<document xmlns="https://untis.at/untis/XmlInterface"><lessons>'
        "<lesson id='LS_100'><periods>1</periods><lesson_subject id='SU_A'/></lesson>"
        "<lesson id='LS_102'><periods>1</periods><lesson_subject id='SU_A'/></lesson>"
        "</lessons></document>",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no contiguas"):
        read_xml(fuente)


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [
        ("", []),
        ("CL_K4A", ["CL_K4A"]),
        ("CL_K4A CL_K4B CL_K4C", ["CL_K4A", "CL_K4B", "CL_K4C"]),
        ("CL_12-GIB 2 CL_12-GIB 3 CL_12-DSDA", ["CL_12-GIB 2", "CL_12-GIB 3", "CL_12-DSDA"]),
        ("a b", ["a", "b"]),
    ],
)
def test_split_refs(raw: str, esperado: list[str]) -> None:
    assert split_refs(raw) == esperado


def test_split_then_strip() -> None:
    """Se parte con el prefijo y después se quita: los espacios internos sobreviven."""
    partes = split_refs("CL_12-GIB 2 CL_12-DSDA")
    assert [strip_prefix(p, "CL_") for p in partes] == ["12-GIB 2", "12-DSDA"]


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [("CL_K1A", "K1A"), ("K1A", "K1A"), ("CL_", "CL_"), ("TR_X", "TR_X"), ("CL_CL_X", "CL_X")],
)
def test_strip_prefix_is_tolerant(raw: str, esperado: str) -> None:
    assert strip_prefix(raw, "CL_") == esperado


def test_add_prefix() -> None:
    assert add_prefix("12-GIB 2", "CL_") == "CL_12-GIB 2"


def test_ids_without_prefix_are_kept_and_prefixed_on_write(tmp_path: Path) -> None:
    """Lectura tolerante: un id sin prefijo se conserva y al escribir lo recibe."""
    fuente = tmp_path / "sin_prefijo.xml"
    fuente.write_text(
        '<document xmlns="https://untis.at/untis/XmlInterface">'
        "<subjects><subject id='MAT'/></subjects>"
        "<classes><class id='1A'/><class id='CL_1B'/></classes>"
        "<lessons><lesson id='LS_100'><periods>1</periods>"
        "<lesson_subject id='SU_MAT'/><lesson_classes id='1A'/></lesson></lessons></document>",
        encoding="utf-8",
    )
    p = read_xml(fuente)
    assert [c.id for c in p.classes] == ["1A", "1B"]
    assert p.subjects[0].id == "MAT"
    assert p.lessons[0].lines[0].classes == ("1A",)
    assert p.lessons[0].lines[0].subject == "MAT"
    salida = tmp_path / "salida.xml"
    write_xml(p, salida)
    texto = salida.read_text(encoding="utf-8")
    assert '<class id="CL_1A" />' in texto
    assert '<lesson_classes id="CL_1A" />' in texto
    _assert_projects_equal(p, read_xml(salida))


def test_field_constants() -> None:
    assert "document/@date" in REGENERATED_FIELDS
    assert "time/assigned_starttime" in REGENERATED_FIELDS
    assert set(DROPPED_FIELDS) == {"holidays", "descriptions", "students"}
    assert not set(DROPPED_FIELDS) & set(REGENERATED_FIELDS)
