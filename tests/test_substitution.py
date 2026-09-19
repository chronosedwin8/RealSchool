"""Sustituciones por ausencia (Vertretungsplanung): día, ausencias y sustitutos.

Tres capas, las tres con pruebas deterministas:

- `untis_model.daily`: lógica pura del día (del horario semanal a la fecha,
  clases afectadas, candidatos ordenados y contadores).
- `application.untis.substitution`: el mixin de la Fachada (altas y bajas,
  parte del día, decisiones, validaciones y deshacer).
- `untis_desktop.windows.substitution`: la ventana, con `qtbot`.

El proyecto de prueba es siempre el mismo colegio pequeño: dos clases, ocho
profesores y seis lecciones colocadas el lunes 5 de octubre de 2026 (y una el
martes), para que cada criterio del orden de candidatos se pueda comprobar por
separado.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest
from PySide6.QtWidgets import QApplication, QTableWidget
from pytestqt.qtbot import QtBot

from scheduling_platform.application import UntisService, UntisSession
from scheduling_platform.untis_model import (
    Absence,
    Assignment,
    EntityKind,
    Holiday,
    Lesson,
    LessonLine,
    PeriodDef,
    Room,
    SchoolClass,
    Subject,
    Substitution,
    SubstitutionKind,
    Supervision,
    SupervisionArea,
    Teacher,
    Term,
    TimeGrid,
    Timetable,
    UntisProject,
    weekday_of,
)
from scheduling_platform.untis_model.daily import (
    affected,
    candidates,
    counters,
    day_lesson,
    day_lessons,
)
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.registry import RibbonTab, load_windows, spec
from untis_desktop.windows import substitution as ventana_mod

#: Lunes 5 de octubre de 2026 y los días siguientes.
LUNES = "20261005"
MARTES = "20261006"
MIERCOLES = "20261007"
DOMINGO = "20261011"


class _Servicio(UntisService):
    """Fachada con el módulo de sustituciones.

    La Fachada va primero a propósito: así la clase vale tanto si `UntisService`
    todavía no hereda el mixin como si ya lo hereda (con el orden al revés, el
    segundo caso sería un error de linealización).
    """


SVC = _Servicio()


# --------------------------------------------------------------------------- #
# Proyecto de prueba
# --------------------------------------------------------------------------- #


def _leccion(numero: int, materia: str, profe: str, clase: str, aula: str) -> Lesson:
    return Lesson(
        number=numero,
        lines=(LessonLine(subject=materia, teacher=profe, classes=(clase,), room=aula),),
        periods_per_week=1,
        time_grid="G",
    )


def _base() -> UntisProject:
    """Colegio pequeño con el horario del lunes ya colocado.

    Lunes: 1ª hora ANA (MAT, 5A, R1) y CARL (MAT, 5B, R3); 2ª hora BEA (ING, 5A,
    R2); 3ª hora DORA (HIS, 5B, R1); 4ª hora FRAN (MAT, 5B, R2).
    Martes: 1ª hora ELI (MAT, 5B, R3), que por eso el lunes no está en el centro.
    GIL y HUGO no dan clase: tendrían que venir. HUGO tiene reserva 5.
    """
    rejilla = TimeGrid(
        "G",
        "Estándar",
        (1, 2, 3, 4, 5),
        tuple(PeriodDef(n, 480 + 60 * (n - 1), 525 + 60 * (n - 1)) for n in range(1, 7)),
    )
    return UntisProject(
        time_grids=(rejilla,),
        classes=(SchoolClass("5A", time_grid="G"), SchoolClass("5B", time_grid="G")),
        teachers=(
            Teacher("ANA"),
            Teacher("BEA"),
            Teacher("CARL"),
            Teacher("DORA"),
            Teacher("ELI"),
            Teacher("FRAN"),
            Teacher("GIL"),
            Teacher("HUGO", substitution_lock=5),
        ),
        rooms=(Room("R1"), Room("R2"), Room("R3"), Room("R4")),
        subjects=(Subject("MAT"), Subject("ING"), Subject("HIS")),
        lessons=(
            _leccion(1, "MAT", "ANA", "5A", "R1"),
            _leccion(2, "ING", "BEA", "5A", "R2"),
            _leccion(3, "MAT", "CARL", "5B", "R3"),
            _leccion(4, "HIS", "DORA", "5B", "R1"),
            _leccion(5, "MAT", "ELI", "5B", "R3"),
            _leccion(6, "MAT", "FRAN", "5B", "R2"),
        ),
        timetables=(
            Timetable(
                "T1",
                "Horario 1",
                (
                    Assignment(1, 0, 1, 1, "R1"),
                    Assignment(2, 0, 1, 2, "R2"),
                    Assignment(3, 0, 1, 1, "R3"),
                    Assignment(4, 0, 1, 3, "R1"),
                    Assignment(5, 0, 2, 1, "R3"),
                    Assignment(6, 0, 1, 4, "R2"),
                ),
            ),
        ),
    )


def _tt(project: UntisProject) -> Timetable:
    horario = project.timetable_by_id("T1")
    assert horario is not None
    return horario


def _con(project: UntisProject, **cambios: object) -> UntisProject:
    return dataclasses.replace(project, **cambios)  # type: ignore[arg-type]


def _ausencia_ana(**cambios: object) -> Absence:
    base = {
        "id": "A-1",
        "entity_kind": EntityKind.TEACHER,
        "entity_id": "ANA",
        "begin": LUNES,
    }
    return Absence(**{**base, **cambios})  # type: ignore[arg-type]


def _sesion(project: UntisProject | None = None) -> UntisSession:
    s = UntisSession(project if project is not None else _base())
    s.active_timetable = "T1"
    return s


# --------------------------------------------------------------------------- #
# Del horario semanal al día: fechas y festivos
# --------------------------------------------------------------------------- #


def test_el_dia_de_la_semana_sale_de_la_fecha() -> None:
    assert weekday_of(LUNES) == 1
    assert weekday_of(DOMINGO) == 7


def test_el_lunes_hay_clase_y_el_domingo_no() -> None:
    p = _base()
    lunes = day_lessons(p, _tt(p), LUNES)
    assert [(c.period, c.lesson_number) for c in lunes] == [(1, 1), (1, 3), (2, 2), (3, 4), (4, 6)]
    assert day_lessons(p, _tt(p), DOMINGO) == ()
    assert day_lessons(p, None, LUNES) == ()


def test_una_clase_del_dia_junta_profesores_clases_y_aula() -> None:
    p = _base()
    clase = day_lesson(p, _tt(p), LUNES, 1, 1)
    assert clase is not None
    assert (clase.subject, clase.teachers, clase.classes, clase.rooms) == (
        "MAT",
        ("ANA",),
        ("5A",),
        ("R1",),
    )
    assert clase.day == 1 and clase.date == LUNES
    assert day_lesson(p, _tt(p), LUNES, 5, 1) is None


def test_un_festivo_deja_el_dia_sin_ninguna_clase() -> None:
    p = _con(_base(), holidays=(Holiday("H-1", "Fiesta local", LUNES, LUNES),))
    assert p.is_holiday(LUNES) and not p.is_holiday(MARTES)
    assert day_lessons(p, _tt(p), LUNES) == ()
    assert day_lessons(p, _tt(p), MARTES) != ()


def test_unas_vacaciones_cubren_todo_el_tramo() -> None:
    p = _con(_base(), holidays=(Holiday("H-1", "Otoño", LUNES, MIERCOLES),))
    for dia in (LUNES, MARTES, MIERCOLES):
        assert p.is_holiday(dia), dia
    assert not p.is_holiday("20261008")


def test_una_leccion_ignorada_o_fuera_de_fechas_no_se_da() -> None:
    p = _base()
    lecciones = list(p.lessons)
    lecciones[0] = dataclasses.replace(lecciones[0], ignore=True)
    lecciones[1] = dataclasses.replace(lecciones[1], effective_begin=MIERCOLES)
    lecciones[2] = dataclasses.replace(lecciones[2], term="T2")
    p = _con(p, lessons=tuple(lecciones), terms=(Term("T2", begin=MARTES, end=MIERCOLES),))
    numeros = [c.lesson_number for c in day_lessons(p, _tt(p), LUNES)]
    assert numeros == [4, 6]


def test_una_fecha_mal_escrita_se_rechaza() -> None:
    p = _base()
    with pytest.raises(ValueError, match="Fecha Untis inválida"):
        day_lessons(p, _tt(p), "5/10/2026")


# --------------------------------------------------------------------------- #
# Ausencias: varios días y horas de inicio y fin
# --------------------------------------------------------------------------- #


def test_una_ausencia_de_un_dia_solo_cubre_ese_dia() -> None:
    a = _ausencia_ana()
    assert a.covers_day(LUNES) and not a.covers_day(MARTES)
    assert a.covers(LUNES, 1) and a.covers(LUNES, 6)


def test_una_ausencia_de_varios_dias_acota_horas_solo_en_los_extremos() -> None:
    a = _ausencia_ana(end=MIERCOLES, first_period=3, last_period=4)
    assert a.last_day == MIERCOLES
    assert not a.covers(LUNES, 2) and a.covers(LUNES, 3)
    assert a.covers(MARTES, 1) and a.covers(MARTES, 6)
    assert a.covers(MIERCOLES, 4) and not a.covers(MIERCOLES, 5)


def test_de_la_ultima_hora_del_lunes_a_la_segunda_del_miercoles() -> None:
    """En varios días las horas acotan días distintos: 5ª -> 2ª es correcto."""
    a = _ausencia_ana(end=MIERCOLES, first_period=5, last_period=2)
    assert not a.covers(LUNES, 4) and a.covers(LUNES, 5) and a.covers(LUNES, 6)
    assert a.covers(MARTES, 1) and a.covers(MARTES, 6)
    assert a.covers(MIERCOLES, 2) and not a.covers(MIERCOLES, 3)
    with pytest.raises(ValueError, match="posterior a la última"):
        _ausencia_ana(first_period=5, last_period=2)


def test_las_ausencias_del_dia_son_las_vigentes() -> None:
    p = _con(
        _base(),
        absences=(
            _ausencia_ana(end=MIERCOLES),
            Absence("A-2", EntityKind.CLASS, "5B", MARTES),
        ),
    )
    assert [a.id for a in p.absences_on(LUNES)] == ["A-1"]
    assert [a.id for a in p.absences_on(MARTES)] == ["A-1", "A-2"]


# --------------------------------------------------------------------------- #
# Clases afectadas
# --------------------------------------------------------------------------- #


def test_la_ausencia_de_un_profesor_afecta_a_sus_clases() -> None:
    p = _con(_base(), absences=(_ausencia_ana(reason="enfermedad"),))
    tocadas = affected(p, _tt(p), LUNES)
    assert len(tocadas) == 1
    uno = tocadas[0]
    assert (uno.lesson.lesson_number, uno.lesson.period) == (1, 1)
    assert uno.teachers == ("ANA",) and uno.absences == ("A-1",)
    assert uno.teacher_missing
    assert uno.reason == "Falta ANA (enfermedad)"


def test_la_ausencia_de_una_clase_y_de_un_aula_tambien_afectan() -> None:
    p = _con(
        _base(),
        absences=(
            Absence("A-1", EntityKind.CLASS, "5B", LUNES, reason="excursión"),
            Absence("A-2", EntityKind.ROOM, "R2", LUNES, first_period=2, last_period=2),
        ),
    )
    tocadas = {a.lesson.lesson_number: a for a in affected(p, _tt(p), LUNES)}
    assert set(tocadas) == {2, 3, 4, 6}
    assert tocadas[3].classes == ("5B",) and not tocadas[3].teachers
    assert tocadas[3].reason == "No asiste la clase 5B (excursión)"
    assert tocadas[2].rooms == ("R2",)
    assert tocadas[2].reason == "No está disponible el aula R2"
    # La lección 6 usa R2 pero a la 4ª hora: solo le afecta la falta de la clase.
    assert tocadas[6].rooms == () and tocadas[6].classes == ("5B",)


def test_una_ausencia_por_horas_solo_afecta_a_esas_horas() -> None:
    p = _con(_base(), absences=(Absence("A-1", EntityKind.TEACHER, "BEA", LUNES, first_period=3),))
    assert affected(p, _tt(p), LUNES) == ()
    p = _con(_base(), absences=(Absence("A-1", EntityKind.TEACHER, "BEA", LUNES, last_period=2),))
    assert [a.lesson.lesson_number for a in affected(p, _tt(p), LUNES)] == [2]


def test_sin_ausencias_o_en_festivo_no_hay_nada_afectado() -> None:
    p = _base()
    assert affected(p, _tt(p), LUNES) == ()
    p = _con(p, absences=(_ausencia_ana(),), holidays=(Holiday("H-1", "Fiesta", LUNES, LUNES),))
    assert affected(p, _tt(p), LUNES) == ()


def test_varias_ausencias_sobre_la_misma_clase_se_juntan_en_el_motivo() -> None:
    p = _con(
        _base(),
        absences=(
            _ausencia_ana(reason="curso"),
            Absence("A-2", EntityKind.ROOM, "R1", LUNES),
        ),
    )
    tocadas = {a.lesson.lesson_number: a for a in affected(p, _tt(p), LUNES)}
    assert tocadas[1].absences == ("A-1", "A-2")
    assert tocadas[1].reason == "Falta ANA (curso); no está disponible el aula R1"


# --------------------------------------------------------------------------- #
# Candidatos: cada criterio del orden
# --------------------------------------------------------------------------- #


def _propuestos(project: UntisProject) -> list[str]:
    return [c.teacher for c in candidates(project, _tt(project), LUNES, 1, 1)]


def test_el_orden_completo_de_los_candidatos() -> None:
    """(b) en el centro, (c) conoce, (d) contador, (e) reserva, y el id al final."""
    p = _con(_base(), absences=(_ausencia_ana(),))
    assert _propuestos(p) == ["BEA", "FRAN", "DORA", "ELI", "GIL", "HUGO"]
    detalle = {c.teacher: c for c in candidates(p, _tt(p), LUNES, 1, 1)}
    assert detalle["BEA"].at_school and detalle["BEA"].teaches_class
    assert detalle["FRAN"].at_school and detalle["FRAN"].teaches_subject
    assert detalle["DORA"].at_school and not detalle["DORA"].knows
    assert detalle["ELI"].knows and not detalle["ELI"].at_school
    assert not detalle["GIL"].knows and not detalle["GIL"].at_school
    assert detalle["BEA"].score > detalle["DORA"].score > detalle["ELI"].score


def test_estar_en_el_centro_pesa_mas_que_conocer_la_materia() -> None:
    p = _con(_base(), absences=(_ausencia_ana(),))
    orden = _propuestos(p)
    assert orden.index("DORA") < orden.index("ELI")


def test_el_contador_decide_entre_dos_iguales() -> None:
    base = _con(_base(), absences=(_ausencia_ana(),))
    assert _propuestos(base)[:2] == ["BEA", "FRAN"]
    con_contador = _con(
        base,
        substitutions=(
            Substitution("S-9", MARTES, 1, 5, SubstitutionKind.SUBSTITUTION, teacher="BEA"),
        ),
    )
    assert _propuestos(con_contador)[:2] == ["FRAN", "BEA"]


def test_la_reserva_de_sustitucion_decide_en_el_ultimo_lugar() -> None:
    p = _con(_base(), absences=(_ausencia_ana(),))
    assert _propuestos(p)[-2:] == ["GIL", "HUGO"]
    # 1-8 solo penalizan: con reserva 8 GIL pasa por detrás de HUGO (reserva 5).
    profes = tuple(
        dataclasses.replace(t, substitution_lock=8) if t.id == "GIL" else t for t in p.teachers
    )
    assert _propuestos(_con(p, teachers=profes))[-2:] == ["HUGO", "GIL"]


def test_nunca_se_propone_a_quien_esta_ocupado_ausente_o_ya_da_la_clase() -> None:
    p = _con(
        _base(),
        absences=(
            _ausencia_ana(),
            Absence("A-2", EntityKind.TEACHER, "DORA", LUNES, first_period=1, last_period=1),
        ),
    )
    propuestos = _propuestos(p)
    assert "CARL" not in propuestos, "CARL da la lección 3 a esa misma hora"
    assert "DORA" not in propuestos, "DORA está ausente esa hora"
    assert "ANA" not in propuestos, "ANA es la profesora de la clase"
    assert propuestos == ["BEA", "FRAN", "ELI", "GIL", "HUGO"]


def test_una_guardia_de_recreo_ocupa_esa_hora_pero_cuenta_como_estar_en_el_centro() -> None:
    p = _con(
        _base(),
        absences=(_ausencia_ana(),),
        supervision_areas=(SupervisionArea("PATIO"),),
        supervisions=(
            Supervision("PATIO", 1, 1, "DORA"),
            Supervision("PATIO", 1, 2, "GIL"),
        ),
    )
    propuestos = _propuestos(p)
    assert "DORA" not in propuestos, "DORA vigila el patio justo a esa hora"
    assert propuestos == ["BEA", "FRAN", "GIL", "ELI", "HUGO"]
    detalle = {c.teacher: c for c in candidates(p, _tt(p), LUNES, 1, 1)}
    assert detalle["GIL"].at_school, "la guardia le obliga a venir ese día"
    assert not detalle["ELI"].at_school


def test_la_guardia_de_otro_dia_no_ocupa_ni_trae_al_profesor() -> None:
    p = _con(
        _base(),
        absences=(_ausencia_ana(),),
        supervision_areas=(SupervisionArea("PATIO"),),
        supervisions=(Supervision("PATIO", 2, 1, "GIL"), Supervision("PATIO", 1, 1, "")),
    )
    detalle = {c.teacher: c for c in candidates(p, _tt(p), LUNES, 1, 1)}
    assert "GIL" in detalle and not detalle["GIL"].at_school
    assert _propuestos(p) == ["BEA", "FRAN", "DORA", "ELI", "GIL", "HUGO"]


def test_la_reserva_9_deja_al_profesor_fuera_de_la_lista() -> None:
    p = _con(_base(), absences=(_ausencia_ana(),))
    profes = tuple(
        dataclasses.replace(t, substitution_lock=9) if t.id in ("BEA", "HUGO") else t
        for t in p.teachers
    )
    p = _con(p, teachers=profes)
    assert _propuestos(p) == ["FRAN", "DORA", "ELI", "GIL"]


def test_quien_ya_cubre_otra_clase_a_esa_hora_deja_de_proponerse() -> None:
    p = _con(
        _base(),
        absences=(_ausencia_ana(), Absence("A-2", EntityKind.TEACHER, "CARL", LUNES)),
        substitutions=(
            Substitution("S-1", LUNES, 1, 3, SubstitutionKind.SUBSTITUTION, teacher="BEA"),
        ),
    )
    assert "BEA" not in _propuestos(p)


def test_sin_clase_a_esa_hora_no_hay_candidatos() -> None:
    p = _base()
    assert candidates(p, _tt(p), LUNES, 5, 1) == ()
    assert candidates(p, None, LUNES, 1, 1) == ()


def test_la_explicacion_del_candidato_esta_en_espanol() -> None:
    p = _con(_base(), absences=(_ausencia_ana(),))
    detalle = {c.teacher: c.reason for c in candidates(p, _tt(p), LUNES, 1, 1)}
    assert detalle["FRAN"] == "Ya está en el centro, da la materia, 0 sustituciones"
    assert detalle["BEA"] == "Ya está en el centro, da clase al grupo, 0 sustituciones"
    assert (
        detalle["HUGO"]
        == "Tendría que venir, no da la materia ni al grupo, 0 sustituciones, reserva 5"
    )


# --------------------------------------------------------------------------- #
# Contadores
# --------------------------------------------------------------------------- #


def test_el_contador_suma_segun_el_tipo_de_decision() -> None:
    p = _con(
        _base(),
        substitutions=(
            Substitution("S-1", LUNES, 1, 1, SubstitutionKind.SUBSTITUTION, teacher="BEA"),
            Substitution("S-2", LUNES, 2, 2, SubstitutionKind.SUPERVISION, teacher="BEA"),
            Substitution("S-3", LUNES, 3, 4, SubstitutionKind.ROOM, teacher="BEA"),
            Substitution("S-4", MARTES, 1, 5, SubstitutionKind.EXTRA, teacher="GIL"),
            Substitution("S-5", MARTES, 2, 6, SubstitutionKind.CANCELLED),
        ),
    )
    assert counters(p) == {"BEA": 2, "GIL": 1}
    assert counters(p, desde=MARTES) == {"GIL": 1}
    assert counters(p, hasta=LUNES) == {"BEA": 2}
    assert counters(p, desde=MIERCOLES) == {}


# --------------------------------------------------------------------------- #
# Fachada: festivos y ausencias
# --------------------------------------------------------------------------- #


def test_fachada_alta_y_baja_de_festivos() -> None:
    s = _sesion()
    assert SVC.add_holiday(s, "Fiesta local", LUNES).ok
    assert SVC.add_holiday(s, "Otoño", MARTES, MIERCOLES).ok
    filas = SVC.holidays(s)
    assert [f.id for f in filas] == ["H-1", "H-2"]
    assert filas[1].label == f"Otoño ({MARTES}-{MIERCOLES})"
    assert SVC.remove_holiday(s, "H-1").ok
    assert [f.id for f in SVC.holidays(s)] == ["H-2"]
    assert not SVC.remove_holiday(s, "H-9").ok


@pytest.mark.parametrize(
    ("nombre", "inicio", "fin", "error"),
    [
        ("", LUNES, "", "nombre"),
        ("X", "2026-10-05", "", "inválida"),
        ("X", "", "", "Falta la fecha"),
        ("X", MIERCOLES, LUNES, "termina antes"),
    ],
)
def test_fachada_valida_los_festivos(nombre: str, inicio: str, fin: str, error: str) -> None:
    s = _sesion()
    resultado = SVC.add_holiday(s, nombre, inicio, fin)
    assert not resultado.ok and error in resultado.message
    assert not s.project.holidays


def test_fachada_alta_de_ausencias_con_ids_automaticos() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES, reason="enfermedad").message == (
        "Ausencia A-1 dada de alta"
    )
    assert (
        SVC.add_absence(s, "class", "5B", LUNES, MIERCOLES).message == "Ausencia A-2 dada de alta"
    )
    filas = SVC.absences(s, LUNES)
    assert [(f.id, f.entity_kind, f.entity_id) for f in filas] == [
        ("A-2", "class", "5B"),
        ("A-1", "teacher", "ANA"),
    ]
    assert filas[1].periods_label == "todo el día"
    assert SVC.absences(s, "20261012") == ()


@pytest.mark.parametrize(
    ("kind", "entidad", "inicio", "fin", "primera", "ultima", "error"),
    [
        ("subject", "MAT", LUNES, "", None, None, "no se puede dar de baja"),
        ("teacher", "ZZZ", LUNES, "", None, None, "no existe"),
        ("teacher", "ANA", "20261340", "", None, None, "inválida"),
        ("teacher", "ANA", MIERCOLES, LUNES, None, None, "termina antes"),
        ("teacher", "ANA", LUNES, "", 0, None, "1 o mayor"),
        ("teacher", "ANA", LUNES, "", 5, 2, "posterior"),
    ],
)
def test_fachada_valida_las_ausencias(
    kind: str,
    entidad: str,
    inicio: str,
    fin: str,
    primera: int | None,
    ultima: int | None,
    error: str,
) -> None:
    s = _sesion()
    resultado = SVC.add_absence(s, kind, entidad, inicio, fin, primera, ultima)
    assert not resultado.ok and error in resultado.message.lower()
    assert not s.project.absences


def test_fachada_baja_de_ausencia_lleva_sus_decisiones() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "BEA").ok
    assert [x.id for x in s.project.substitutions] == ["S-1"]
    assert SVC.remove_absence(s, "A-1").ok
    assert not s.project.absences and not s.project.substitutions
    assert not SVC.remove_absence(s, "A-1").ok


# --------------------------------------------------------------------------- #
# Fachada: parte del día
# --------------------------------------------------------------------------- #


def test_fachada_parte_del_dia_con_una_ausencia() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES, reason="enfermedad").ok
    parte = SVC.day_report(s, LUNES)
    assert parte.weekday == 1 and parte.timetable == "T1" and not parte.is_holiday
    assert len(parte.rows) == 1
    fila = parte.rows[0]
    assert (fila.period, fila.lesson, fila.subject) == (1, 1, "MAT")
    assert fila.absent_teachers == ("ANA",) and fila.absence == "A-1"
    assert fila.pending and not fila.decided
    assert parte.pending == 1
    assert [a.id for a in parte.absences] == ["A-1"]


def test_fachada_parte_del_dia_vacio_festivo_y_fecha_mala() -> None:
    s = _sesion()
    assert SVC.day_report(s, LUNES).message == "Ningún cambio este día"
    assert SVC.add_holiday(s, "Fiesta", LUNES).ok
    parte = SVC.day_report(s, LUNES)
    assert parte.is_holiday and parte.holiday == "Fiesta" and parte.rows == ()
    mala = SVC.day_report(s, "lunes")
    assert mala.weekday == 0 and "inválida" in mala.message
    sin_horario = UntisSession(_base())
    assert "horario activo" in SVC.day_report(sin_horario, LUNES).message


def test_fachada_el_parte_tambien_muestra_las_decisiones_sin_ausencia() -> None:
    s = _sesion()
    assert SVC.change_room(s, LUNES, 2, 2, "R4").ok
    parte = SVC.day_report(s, LUNES)
    assert [(f.lesson, f.kind, f.new_room) for f in parte.rows] == [(2, "room", "R4")]
    assert parte.rows[0].kind_label == "Cambio de aula" and not parte.rows[0].pending


# --------------------------------------------------------------------------- #
# Fachada: decisiones
# --------------------------------------------------------------------------- #


def test_fachada_propone_candidatos_ordenados_con_su_explicacion() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    filas = SVC.substitute_candidates(s, LUNES, 1, 1)
    assert [f.teacher for f in filas] == ["BEA", "FRAN", "DORA", "ELI", "GIL", "HUGO"]
    assert filas[0].reason.startswith("Ya está en el centro")
    assert filas[0].score > filas[-1].score
    assert SVC.substitute_candidates(s, "mal", 1, 1) == ()


def test_fachada_asigna_sustituto_y_lo_apunta_en_el_contador() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "BEA", note="avisada").ok
    decision = s.project.substitutions[0]
    assert decision.id == "S-1" and decision.teacher == "BEA"
    assert decision.absent_teacher == "ANA" and decision.absence == "A-1"
    assert decision.note == "avisada" and decision.counts == 1
    parte = SVC.day_report(s, LUNES)
    assert parte.rows[0].substitute == "BEA" and not parte.rows[0].pending
    contadores = {c.teacher: c for c in SVC.substitution_counters(s)}
    assert contadores["BEA"].count == 1 and contadores["BEA"].assigned == 1
    assert contadores["GIL"].count == 0


def test_fachada_corregir_una_decision_conserva_su_id() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "BEA").ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "FRAN").ok
    assert [(x.id, x.teacher) for x in s.project.substitutions] == [("S-1", "FRAN")]


@pytest.mark.parametrize(
    ("hora", "leccion", "profesor", "error"),
    [
        (1, 1, "ZZZ", "no existe"),
        (5, 1, "BEA", "no se da"),
        (1, 99, "BEA", "no se da"),
        (1, 1, "CARL", "no puede cubrir esa hora"),
        (1, 1, "ANA", "no puede cubrir esa hora"),
    ],
)
def test_fachada_valida_la_asignacion(hora: int, leccion: int, profesor: str, error: str) -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    resultado = SVC.assign_substitute(s, LUNES, hora, leccion, profesor)
    assert not resultado.ok and error in resultado.message
    assert not s.project.substitutions


def test_fachada_una_guardia_de_recreo_saca_al_profesor_de_los_candidatos() -> None:
    s = _sesion(
        _con(
            _base(),
            supervision_areas=(SupervisionArea("PATIO"),),
            supervisions=(Supervision("PATIO", 1, 1, "BEA"),),
        )
    )
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert SVC.substitute_candidates(s, LUNES, 1, 1)[0].teacher == "FRAN"
    rechazo = SVC.assign_substitute(s, LUNES, 1, 1, "BEA")
    assert not rechazo.ok and "no puede cubrir esa hora" in rechazo.message
    assert SVC.assign_substitute(s, LUNES, 1, 1, "BEA", force=True).ok


def test_fachada_la_reserva_9_solo_se_salta_a_la_fuerza() -> None:
    profes = tuple(
        dataclasses.replace(t, substitution_lock=9) if t.id == "BEA" else t
        for t in _base().teachers
    )
    s = _sesion(_con(_base(), teachers=profes))
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert "BEA" not in [f.teacher for f in SVC.substitute_candidates(s, LUNES, 1, 1)]
    assert not SVC.assign_substitute(s, LUNES, 1, 1, "BEA").ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "BEA", force=True).ok


def test_fachada_admite_la_ausencia_de_varios_dias_con_horas_cruzadas() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES, MIERCOLES, 5, 2).ok
    ausencia = s.project.absences[0]
    assert ausencia.covers(LUNES, 5) and not ausencia.covers(LUNES, 4)
    assert ausencia.covers(MIERCOLES, 2) and not ausencia.covers(MIERCOLES, 3)


def test_fachada_asignar_a_la_fuerza_y_tipos_de_decision() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert not SVC.assign_substitute(s, LUNES, 1, 1, "CARL").ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "CARL", force=True).ok
    assert not SVC.assign_substitute(s, LUNES, 1, 1, "BEA", kind="raro").ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "BEA", kind="supervision").ok
    assert s.project.substitutions[0].kind is SubstitutionKind.SUPERVISION
    assert not SVC.assign_substitute(s, "20261340", 1, 1, "BEA").ok


def test_fachada_en_festivo_no_se_decide_nada() -> None:
    s = _sesion()
    assert SVC.add_holiday(s, "Fiesta", LUNES).ok
    resultado = SVC.assign_substitute(s, LUNES, 1, 1, "BEA")
    assert not resultado.ok and "no hay clase" in resultado.message


def test_fachada_suprimir_una_clase() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert SVC.cancel_lesson(s, LUNES, 1, 1, note="sin sustituto").ok
    decision = s.project.substitutions[0]
    assert decision.kind is SubstitutionKind.CANCELLED and decision.teacher == ""
    assert decision.counts == 0 and decision.absent_teacher == "ANA"
    fila = SVC.day_report(s, LUNES).rows[0]
    assert fila.kind_label == "Clase suprimida" and not fila.pending
    assert not SVC.cancel_lesson(s, LUNES, 5, 1).ok


def test_fachada_cambiar_de_aula_con_sus_validaciones() -> None:
    s = _sesion()
    assert not SVC.change_room(s, LUNES, 1, 1, "R9").ok
    ocupada = SVC.change_room(s, LUNES, 1, 1, "R3")
    assert not ocupada.ok and "ocupada por la lección 3" in ocupada.message
    assert SVC.change_room(s, LUNES, 1, 1, "R3", force=True).ok
    assert SVC.change_room(s, LUNES, 1, 1, "R4").ok
    assert s.project.substitutions[0].room == "R4"
    assert not SVC.change_room(s, "mal", 1, 1, "R4").ok


def test_fachada_un_aula_ausente_o_ya_asignada_no_vale() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "room", "R4", LUNES).ok
    ausente = SVC.change_room(s, LUNES, 1, 1, "R4")
    assert not ausente.ok and "también está ausente" in ausente.message
    assert SVC.change_room(s, LUNES, 1, 3, "R2").ok
    repetida = SVC.change_room(s, LUNES, 1, 1, "R2")
    assert not repetida.ok and "ya se ha asignado" in repetida.message


def test_fachada_quitar_una_decision() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert not SVC.clear_decision(s, LUNES, 1, 1).ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "BEA").ok
    assert SVC.clear_decision(s, LUNES, 1, 1).ok
    assert not s.project.substitutions
    assert SVC.day_report(s, LUNES).rows[0].pending


def test_fachada_contadores_por_tramo_de_fechas() -> None:
    s = _sesion()
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "BEA").ok
    assert SVC.add_absence(s, "teacher", "ELI", MARTES).ok
    assert SVC.assign_substitute(s, MARTES, 1, 5, "BEA").ok
    filas = {c.teacher: c for c in SVC.substitution_counters(s)}
    assert filas["BEA"].count == 2 and filas["BEA"].assigned == 2
    solo_martes = {c.teacher: c for c in SVC.substitution_counters(s, begin=MARTES)}
    assert solo_martes["BEA"].count == 1
    assert SVC.substitution_counters(s)[0].teacher == "BEA"
    assert filas["HUGO"].lock == 5


# --------------------------------------------------------------------------- #
# Deshacer
# --------------------------------------------------------------------------- #


def test_deshacer_todas_las_ediciones_del_modulo() -> None:
    s = _sesion()
    assert SVC.add_holiday(s, "Fiesta", MIERCOLES).ok
    assert SVC.add_absence(s, "teacher", "ANA", LUNES).ok
    assert SVC.assign_substitute(s, LUNES, 1, 1, "BEA").ok
    assert s.undo_label == "Sustituir ANA por BEA"
    assert SVC.undo(s) and not s.project.substitutions
    assert SVC.undo(s) and not s.project.absences
    assert SVC.undo(s) and not s.project.holidays
    assert not s.can_undo
    assert SVC.redo(s) and [h.name for h in s.project.holidays] == ["Fiesta"]


# --------------------------------------------------------------------------- #
# Ventana de escritorio
# --------------------------------------------------------------------------- #


@pytest.fixture
def bridge(qapp: QApplication) -> Iterator[FacadeBridge]:
    b = FacadeBridge(SVC)
    yield b
    b.set_language("es")


@pytest.fixture
def ventana(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> ventana_mod.SubstitutionWindow:
    bridge.attach(_sesion())
    w = ventana_mod.SubstitutionWindow(bridge)
    qtbot.addWidget(w)
    w.set_date(LUNES)
    w.refresh()
    qapp.processEvents()
    return w


def _texto(tabla: QTableWidget, fila: int, columna: int) -> str:
    """Texto de una celda (el `item` de Qt puede ser `None`)."""
    celda = tabla.item(fila, columna)
    assert celda is not None, (fila, columna)
    return str(celda.text())


def test_ventana_registrada_en_la_cinta() -> None:
    load_windows()
    s = spec("substitution")
    assert s.tab is RibbonTab.MODULES and s.icon == "swap"
    assert len(s.tooltip) > 20 and s.tooltip.endswith(".")
    assert s.title_de and s.tooltip_de


def test_ventana_sin_proyecto_no_falla(qtbot: QtBot, qapp: QApplication) -> None:
    w = ventana_mod.SubstitutionWindow(FacadeBridge(SVC))
    qtbot.addWidget(w)
    qapp.processEvents()
    assert w.day_table.rowCount() == 0 and w.report is None
    assert not w.propose().ok and not w.remove_absence().ok


def test_ventana_da_de_alta_una_ausencia_y_muestra_el_parte(
    ventana: ventana_mod.SubstitutionWindow, qapp: QApplication
) -> None:
    assert ventana.date == LUNES
    assert ventana.day_table.rowCount() == 0
    assert ventana.add_absence("teacher", "ANA", LUNES, reason="enfermedad").ok
    qapp.processEvents()
    assert ventana.absence_table.rowCount() == 1
    assert _texto(ventana.absence_table, 0, 0) == "ANA"
    assert _texto(ventana.absence_table, 0, 2) == "05/10/2026"
    assert ventana.day_table.rowCount() == 1
    assert _texto(ventana.day_table, 0, 1) == "1"
    assert "por resolver" in ventana.weekday_label.text()


def test_ventana_propone_candidatos_y_asigna(
    ventana: ventana_mod.SubstitutionWindow, qapp: QApplication
) -> None:
    assert ventana.add_absence("teacher", "ANA", LUNES).ok
    ventana.day_table.selectRow(0)
    filas = ventana.candidates()
    assert [f.teacher for f in filas] == ["BEA", "FRAN", "DORA", "ELI", "GIL", "HUGO"]
    dialogo = ventana_mod.CandidatesDialog(filas, ventana)
    assert dialogo.teacher == "BEA"
    assert _texto(dialogo.table, 0, 3).startswith("Ya está en el centro")
    assert ventana.assign("BEA").ok
    qapp.processEvents()
    assert _texto(ventana.day_table, 0, 7) == "BEA"
    assert _texto(ventana.counter_table, 0, 0) == "BEA"
    assert _texto(ventana.counter_table, 0, 1) == "1"


def test_ventana_suprime_cambia_de_aula_y_quita_la_decision(
    ventana: ventana_mod.SubstitutionWindow, qapp: QApplication
) -> None:
    assert ventana.add_absence("teacher", "ANA", LUNES).ok
    ventana.day_table.selectRow(0)
    assert ventana.cancel_lesson().ok
    qapp.processEvents()
    assert _texto(ventana.day_table, 0, 6) == "Clase suprimida"
    ventana.day_table.selectRow(0)
    assert ventana.change_room("R4").ok
    qapp.processEvents()
    assert _texto(ventana.day_table, 0, 5) == "R4"
    ventana.day_table.selectRow(0)
    assert ventana.clear_decision().ok
    qapp.processEvents()
    assert _texto(ventana.day_table, 0, 6) == ""
    assert not ventana.change_room("R9").ok


def test_ventana_festivo_y_cambio_de_dia(
    ventana: ventana_mod.SubstitutionWindow, qapp: QApplication
) -> None:
    assert ventana.bridge.edit(lambda: SVC.add_holiday(ventana.bridge.session, "Fiesta", LUNES)).ok
    ventana.refresh()
    qapp.processEvents()
    assert "sin clase: Fiesta" in ventana.weekday_label.text()
    ventana.next_day()
    qapp.processEvents()
    assert ventana.date == MARTES
    assert ventana.report is not None and not ventana.report.is_holiday
    ventana.previous_day()
    assert ventana.date == LUNES


def test_ventana_marca_y_quita_el_dia_sin_clase(
    ventana: ventana_mod.SubstitutionWindow, qapp: QApplication
) -> None:
    """El botón de la barra es la única forma de tocar el calendario del curso."""
    assert not ventana.is_holiday()
    assert ventana.holiday_button.text() == "Día sin clase"

    assert ventana.toggle_holiday().ok
    qapp.processEvents()
    assert ventana.is_holiday()
    assert ventana.holiday_button.text() == "Devolver la clase"
    assert ventana.report is not None and ventana.report.is_holiday
    assert not ventana.report.rows  # un día sin clase no tiene nada que sustituir

    assert ventana.toggle_holiday().ok
    qapp.processEvents()
    assert not ventana.is_holiday()
    assert ventana.holiday_button.text() == "Día sin clase"
    assert not ventana.bridge.session.project.holidays

    # Y se deshace como cualquier otro cambio.
    assert ventana.toggle_holiday().ok
    SVC.undo(ventana.bridge.session)
    ventana.refresh()
    assert not ventana.is_holiday()


def test_ventana_dialogo_de_ausencia_trae_los_datos(
    qtbot: QtBot, ventana: ventana_mod.SubstitutionWindow
) -> None:
    dialogo = ventana_mod.AbsenceDialog(ventana.bridge, LUNES, ventana)
    qtbot.addWidget(dialogo)
    assert dialogo.kind == "teacher"
    assert dialogo.entity == "ANA"
    dialogo.kind_combo.setCurrentIndex(2)
    assert dialogo.kind == "room" and dialogo.entity == "R1"
    dialogo.kind_combo.setCurrentIndex(0)
    dialogo.first_period.setValue(3)
    kind, entidad, inicio, fin, primera, ultima, _motivo = dialogo.values()
    assert (kind, entidad, inicio, fin, primera, ultima) == (
        "teacher",
        "ANA",
        LUNES,
        LUNES,
        3,
        None,
    )


def test_ventana_en_aleman_conserva_los_datos(
    ventana: ventana_mod.SubstitutionWindow, qapp: QApplication
) -> None:
    assert ventana.add_absence("teacher", "ANA", LUNES).ok
    ventana.bridge.set_language("de")
    qapp.processEvents()
    assert ventana.day_table.rowCount() == 1
    assert ventana.counter_table.rowCount() == len(ventana.bridge.session.project.teachers)
