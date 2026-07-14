"""Importador de exports reales de Untis (DS-04 Colegio Alemán).

Se prueba con un XML sintético que reproduce las rarezas del export real:
jornadas con **horas de reloj distintas para el mismo número de período**,
co-docencia, clases acopladas y obligaciones sin curso.
"""

from __future__ import annotations

from pathlib import Path

from scheduling_platform.engine import ValidationEngine
from scheduling_platform.untis import (
    UntisToCanonicalAdapter,
    parse_untis,
    untis_reference_solution,
)

# Dos jornadas. Ojo al período 2: en Kinder es 09:00-09:45 y en Bachi es un
# recreo de 09:00 a 09:15. El período 3 de Bachi (09:15-10:00) SÍ se solapa en
# reloj con el período 2 de Kinder.
XML = """<?xml version="1.0" encoding="UTF-8"?>
<document version="3.0" xmlns="https://untis.at/untis/XmlInterface">
  <general><header1>Colegio de Prueba</header1></general>
  <timeperiods>
    <timeperiod id="a"><day>1</day><period>1</period><starttime>0800</starttime>
      <endtime>0845</endtime><timegrid>Kinder</timegrid></timeperiod>
    <timeperiod id="b"><day>1</day><period>2</period><starttime>0900</starttime>
      <endtime>0945</endtime><timegrid>Kinder</timegrid></timeperiod>
    <timeperiod id="c"><day>1</day><period>1</period><starttime>0800</starttime>
      <endtime>0845</endtime><timegrid>Bachi</timegrid></timeperiod>
    <timeperiod id="d"><day>1</day><period>2</period><starttime>0900</starttime>
      <endtime>0915</endtime><timegrid>Bachi</timegrid></timeperiod>
    <timeperiod id="e"><day>1</day><period>3</period><starttime>0915</starttime>
      <endtime>1000</endtime><timegrid>Bachi</timegrid></timeperiod>
  </timeperiods>
  <rooms>
    <room id="RM_1"><longname>Aula 1</longname></room>
  </rooms>
  <teachers>
    <teacher id="TR_A"><forename>Ana</forename></teacher>
    <teacher id="TR_B"><forename>Bruno</forename></teacher>
  </teachers>
  <subjects>
    <subject id="SU_MAT"><longname>Mate</longname></subject>
  </subjects>
  <classes>
    <class id="CL_1"><longname>1A</longname><timegrid>Kinder</timegrid></class>
    <class id="CL_2"><longname>2A</longname><timegrid>Bachi</timegrid></class>
  </classes>
  <lessons>
    <lesson id="LS_1"><periods>1</periods><lesson_subject id="SU_MAT"/>
      <lesson_teacher id="TR_A"/><lesson_classes id="CL_1"/>
      <lesson_studentgroups id="SG_1"/><timegrid>Kinder</timegrid>
      <times><time><assigned_day>1</assigned_day><assigned_period>1</assigned_period>
        <assigned_room id="RM_1"/></time></times></lesson>
    <lesson id="LS_2"><periods>1</periods><lesson_subject id="SU_MAT"/>
      <lesson_teacher id="TR_B"/><lesson_classes id="CL_1"/>
      <lesson_studentgroups id="SG_1"/><timegrid>Kinder</timegrid>
      <times><time><assigned_day>1</assigned_day><assigned_period>1</assigned_period>
        </time></times></lesson>
    <lesson id="LS_3"><periods>1</periods><lesson_subject id="SU_MAT"/>
      <lesson_teacher id="TR_A"/><timegrid>Kinder</timegrid>
      <times><time><assigned_day>1</assigned_day><assigned_period>2</assigned_period>
        </time></times></lesson>
  </lessons>
</document>
"""


def _export(tmp_path: Path):  # type: ignore[no-untyped-def]
    ruta = tmp_path / "untis.xml"
    ruta.write_text(XML, encoding="utf-8")
    return parse_untis(ruta)


# --- Parser ---


def test_lee_las_entidades(tmp_path: Path) -> None:
    export = _export(tmp_path)
    assert export.school == "Colegio de Prueba"
    assert len(export.teachers) == 2
    assert len(export.classes) == 2
    assert len(export.lessons) == 3
    assert export.total_periods == 3


def test_lee_las_horas_de_reloj(tmp_path: Path) -> None:
    export = _export(tmp_path)
    kinder2 = export.period_at("Kinder", 1, 2)
    bachi2 = export.period_at("Bachi", 1, 2)
    assert kinder2 is not None and bachi2 is not None
    # MISMO número de período, horas DISTINTAS: 45 min frente a un recreo de 15
    assert (kinder2.start_min, kinder2.duration) == (9 * 60, 45)
    assert (bachi2.start_min, bachi2.duration) == (9 * 60, 15)


def test_la_rejilla_es_de_reloj_no_de_periodos(tmp_path: Path) -> None:
    translation = UntisToCanonicalAdapter().translate(_export(tmp_path))
    # el día va de 08:00 a 10:00 -> 120 minutos, no "3 períodos"
    assert translation.problem.horizon == 120
    assert translation.hhmm(0) == "08:00"


# --- Adaptador ---


def test_fusiona_la_co_docencia(tmp_path: Path) -> None:
    translation = UntisToCanonicalAdapter().translate(_export(tmp_path))
    # LS_1 y LS_2 comparten grupo de estudiantes: son la misma clase con 2 docentes
    codocentes = [c for c in translation.courses if len(c.teacher_ids) > 1]
    assert len(codocentes) == 1
    assert set(codocentes[0].teacher_ids) == {"TR_A", "TR_B"}


def test_excluye_las_obligaciones_sin_curso(tmp_path: Path) -> None:
    export = _export(tmp_path)
    # LS_3 no tiene curso: es una obligación no lectiva
    sin_deberes = UntisToCanonicalAdapter().translate(export)
    con_deberes = UntisToCanonicalAdapter(include_duties=True).translate(export)
    assert len(sin_deberes.problem.tasks) == 1  # solo la clase real (co-docente)
    assert len(con_deberes.problem.tasks) == 2


def test_la_tarea_dura_lo_que_dura_su_periodo(tmp_path: Path) -> None:
    translation = UntisToCanonicalAdapter().translate(_export(tmp_path))
    tarea = translation.problem.tasks[0]
    assert tarea.duration == 45  # minutos reales, no "1 período"
    # requiere sus dos docentes, su curso y un aula
    tags = {r.tag for r in tarea.requirements}
    assert "teacher#TR_A" in tags
    assert "teacher#TR_B" in tags
    assert "group#CL_1" in tags


# --- Solución de referencia (auditoría) ---


def test_reconstruye_el_horario_de_untis(tmp_path: Path) -> None:
    translation = UntisToCanonicalAdapter().translate(_export(tmp_path))
    referencia, sin_ubicar = untis_reference_solution(translation)
    assert sin_ubicar == 0
    assert len(referencia.assignments) == 1
    # Untis la puso en el período 1 de Kinder = 08:00 = slot 0
    assert int(referencia.assignments[0].start) == 0


def test_audita_el_horario_de_untis(tmp_path: Path) -> None:
    translation = UntisToCanonicalAdapter().translate(_export(tmp_path))
    referencia, _ = untis_reference_solution(translation)
    reporte = ValidationEngine().validate(translation.problem, referencia)
    assert reporte.valid  # este horario de juguete sí es correcto
