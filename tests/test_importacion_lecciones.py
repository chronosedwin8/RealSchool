"""Carga masiva de lecciones: acoples, alta frente a actualización y la ventana.

El formato es el de `application.untis.bulk_lessons`: una fila por línea de
acople y el número de lección como pegamento. Aquí se comprueba que agrupa bien
las líneas, que numera solas las lecciones nuevas, que valida como la ventana
(materia, clases, horas > 0, columnas de la lección iguales en todas sus
líneas), que todo entra en un solo paso de deshacer y que exportar e importar
las 709 lecciones del proyecto seudonimizado no pierde nada.

Las pruebas trabajan sobre `_Servicio`, que es la Fachada tal cual (ya hereda
`BulkLessonsMixin`), para que se vea desde dónde lo usa la UI.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from scheduling_platform.application import MasterKind, UntisService, UntisSession
from scheduling_platform.application.untis.bulk import import_master, table_from_rows
from scheduling_platform.application.untis.bulk_lessons import (
    LESSON_COLUMNS,
    LESSON_FIELDS,
    export_lessons,
    lesson_column_map,
    lesson_rows,
    preview_lessons,
)
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.windows.lessons import LessonsWindow


class _Servicio(UntisService):
    """La Fachada con los dos trozos de carga masiva ya heredados."""


SVC = _Servicio()

#: Encabezado técnico completo, para escribir CSV de prueba sin ambigüedad.
CABECERA = ";".join(LESSON_FIELDS)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _demo() -> UntisSession:
    """Proyecto con datos maestros suficientes para colgar lecciones de ellos."""
    s = SVC.new("Colegio Demo")
    import_master(s, MasterKind.ROOMS, "id\nR1\nR2\nLAB\n")
    import_master(s, MasterKind.SUBJECTS, "id\nMAT\nFIS\nMUS\nDEP\n")
    import_master(s, MasterKind.CLASSES, "id;home_room\n5A;R1\n5B;R2\n")
    import_master(s, MasterKind.TEACHERS, "id\nANA\nBEA\nCAR\n")
    import_master(s, MasterKind.STUDENT_GROUPS, "id;subject;classes\nG1;MUS;5A, 5B\n")
    return UntisSession(s.project)


@pytest.fixture
def demo() -> UntisSession:
    return _demo()


@pytest.fixture(scope="module")
def anon(anon_xml_path: Path) -> UntisSession:
    return SVC.open(anon_xml_path)


@pytest.fixture
def bridge(qapp: QApplication) -> Iterator[FacadeBridge]:
    b = FacadeBridge(SVC)
    b.attach(_demo())
    qapp.processEvents()
    yield b
    b.set_language("es")


def _make[W: QWidget](qtbot: QtBot, widget: W) -> W:
    qtbot.addWidget(widget)
    return widget


def _numeros(session: UntisSession) -> list[int]:
    return [le.number for le in session.project.lessons]


def _leccion(session: UntisSession, numero: int) -> object:
    return session.project.lesson_by_number[numero]


# --------------------------------------------------------------------------- #
# Formato y correspondencia de columnas
# --------------------------------------------------------------------------- #


def test_el_formato_acepta_nombres_espanoles_alemanes_y_tecnicos() -> None:
    mapa = lesson_column_map()
    for nombre in ("leccion", "Lección", "UNTERRICHT", "lesson", "nr"):
        assert mapa[_n(nombre)].field == "lesson"
    for nombre in ("horas_semana", "Horas/semana", "Std./Woche", "periods_per_week"):
        assert mapa[_n(nombre)].field == "periods_per_week"
    for nombre in ("grupo_alumnos", "Grupo de alumnos", "Schülergruppe", "student_group"):
        assert mapa[_n(nombre)].field == "student_group"
    assert mapa[_n("dobles_min")].field == "double_periods_min"
    assert [c.field for c in LESSON_COLUMNS[:4]] == ["lesson", "subject", "teacher", "classes"]


def _n(texto: str) -> str:
    from scheduling_platform.application.untis.bulk import normalize

    return normalize(texto)


# --------------------------------------------------------------------------- #
# Alta, acoples y numeración
# --------------------------------------------------------------------------- #


def test_alta_simple_con_encabezado_en_espanol(demo: UntisSession) -> None:
    informe = SVC.import_lessons(
        demo,
        "Lección;Materia;Profesor;Clases;Horas/semana\n;MAT;ANA;5A;4\n;FIS;BEA;5A, 5B;2\n",
    )
    assert informe.applied and informe.created == ("1", "2")
    primera = demo.project.lessons[0]
    assert primera.number == 1 and primera.periods_per_week == 4
    assert primera.lines[0].subject == "MAT" and primera.lines[0].teacher == "ANA"
    assert demo.project.lessons[1].lines[0].classes == ("5A", "5B")


def test_las_filas_con_el_mismo_numero_forman_un_acople(demo: UntisSession) -> None:
    texto = (
        "Lección;Materia;Profesor;Clases;Grupo de alumnos;Horas/semana\n"
        "10;MUS;ANA;5A;G1;2\n"
        "10;MUS;BEA;5B;G1;\n"
        "10;MUS;CAR;5A, 5B;;\n"
        "11;MAT;ANA;5A;;4\n"
    )
    assert SVC.import_lessons(demo, texto).created == ("10", "11")
    acople = demo.project.lesson_by_number[10]
    assert len(acople.lines) == 3 and acople.periods_per_week == 2
    assert [x.teacher for x in acople.lines] == ["ANA", "BEA", "CAR"]
    assert acople.lines[0].student_group == "G1"
    assert len(demo.project.lesson_by_number[11].lines) == 1


def test_una_clave_de_texto_acopla_lecciones_nuevas(demo: UntisSession) -> None:
    texto = (
        "Lección;Materia;Profesor;Clases;Horas/semana\n"
        "ib-mus;MUS;ANA;5A;3\nib-mus;MUS;BEA;5B;\n;MAT;CAR;5A;4\n"
    )
    informe = SVC.import_lessons(demo, texto)
    assert informe.created == ("1", "2") and informe.ok
    assert len(demo.project.lesson_by_number[1].lines) == 2
    assert len(demo.project.lesson_by_number[2].lines) == 1


def test_el_numero_libre_sigue_al_mayor_que_ya_hay(demo: UntisSession) -> None:
    SVC.import_lessons(demo, "Lección;Materia;Clases;Horas/semana\n50;MAT;5A;2\n")
    SVC.import_lessons(demo, "Lección;Materia;Clases;Horas/semana\n;FIS;5A;2\n;MUS;5A;2\n")
    assert _numeros(demo) == [50, 51, 52]


def test_un_numero_que_no_existe_se_crea_con_ese_numero(demo: UntisSession) -> None:
    assert SVC.import_lessons(demo, f"{CABECERA}\n900;MAT;ANA;5A;;;;;3\n").created == ("900",)
    assert _numeros(demo) == [900]


# --------------------------------------------------------------------------- #
# Actualización
# --------------------------------------------------------------------------- #


def test_un_numero_que_existe_actualiza_la_leccion_entera(demo: UntisSession) -> None:
    SVC.import_lessons(
        demo,
        "Lección;Materia;Profesor;Clases;Horas/semana\n7;MAT;ANA;5A;4\n7;MAT;BEA;5B;\n",
    )
    informe = SVC.import_lessons(
        demo, "Lección;Materia;Profesor;Clases;Horas/semana\n7;FIS;CAR;5A;6\n"
    )
    assert informe.updated == ("7",) and informe.applied
    leccion = demo.project.lesson_by_number[7]
    assert len(leccion.lines) == 1 and leccion.lines[0].subject == "FIS"
    assert leccion.periods_per_week == 6


def test_una_leccion_igual_no_cuenta_como_cambio(demo: UntisSession) -> None:
    SVC.import_lessons(demo, "Lección;Materia;Clases;Horas/semana\n;MAT;5A;4\n")
    antes = demo.project
    informe = SVC.import_lessons(demo, export_lessons(demo))
    assert informe.unchanged == ("1",) and not informe.applied
    assert demo.project is antes


def test_actualizar_conserva_lo_que_la_tabla_no_lleva(demo: UntisSession) -> None:
    """Período, fechas de vigencia y secuencia siguen ahí tras reimportar."""
    import dataclasses

    SVC.import_lessons(demo, "Lección;Materia;Clases;Horas/semana\n1;MAT;5A;4\n")
    rica = dataclasses.replace(
        demo.project.lesson_by_number[1], term="P1", effective_begin="20260901"
    )
    demo.project = dataclasses.replace(demo.project, lessons=(rica,))
    SVC.import_lessons(demo, "Lección;Materia;Clases;Horas/semana\n1;FIS;5A;5\n")
    leccion = demo.project.lesson_by_number[1]
    assert (leccion.term, leccion.effective_begin) == ("P1", "20260901")
    assert leccion.lines[0].subject == "FIS" and leccion.periods_per_week == 5


# --------------------------------------------------------------------------- #
# Errores
# --------------------------------------------------------------------------- #


def test_materia_inexistente_deja_fuera_la_leccion(demo: UntisSession) -> None:
    informe = SVC.import_lessons(
        demo, "Lección;Materia;Clases;Horas/semana\n;MAT;5A;4\n;NOEXISTE;5A;2\n"
    )
    assert informe.created == ("1",) and informe.rows_failed == 1
    assert "'NOEXISTE' no existe" in informe.summary()
    assert _numeros(demo) == [1]


def test_clase_inexistente_y_materia_vacia(demo: UntisSession) -> None:
    informe = SVC.import_lessons(demo, "Lección;Materia;Clases;Horas/semana\n;MAT;5Z;4\n;;5A;2\n")
    assert not informe.applied and informe.rows_failed == 2
    motivos = informe.summary()
    assert "la clase '5Z' no existe: créala antes en Datos maestros -> Clases" in motivos
    assert "necesita materia" in motivos


def test_lo_que_falta_se_resume_y_dice_que_hacer_antes(demo: UntisSession) -> None:
    """Importar lecciones en un proyecto sin datos maestros: qué dar de alta antes."""
    SVC.import_lessons(
        demo,
        "Lección;Materia;Profesor;Clases;Aula;Horas/semana\n;MAT;ANA;5A;R1;4\n;FIS;BEA;5B;LAB;2\n",
    )
    csv = SVC.export_lessons(demo)

    vacio = SVC.new("Colegio Nuevo")
    previo = SVC.preview_lessons(vacio, csv)
    assert not previo.applied and previo.rows_failed == 2
    resumen = previo.missing_summary()
    assert "2 materias: MAT, FIS" in resumen and "2 profesores: ANA, BEA" in resumen
    assert "2 clases: 5A, 5B" in resumen and "2 aulas: R1, LAB" in resumen
    assert resumen in previo.summary()
    assert "la materia 'MAT' no existe: créala antes en Datos maestros -> Materias" in (
        previo.summary()
    )
    assert SVC.import_lessons(vacio, csv).missing == previo.missing


def test_horas_a_cero_o_negativas(demo: UntisSession) -> None:
    informe = SVC.import_lessons(demo, "Lección;Materia;Clases;Horas/semana\n;MAT;5A;0\n")
    assert not informe.applied and "mayores que cero" in informe.summary()
    assert not SVC.import_lessons(demo, "Lección;Materia;Clases;Horas/semana\n;MAT;5A;-2\n").applied
    assert not demo.project.lessons


def test_horas_distintas_en_lineas_de_la_misma_leccion(demo: UntisSession) -> None:
    texto = (
        "Lección;Materia;Profesor;Clases;Horas/semana\n"
        "3;MAT;ANA;5A;4\n"
        "3;MAT;BEA;5B;6\n"
        "4;FIS;CAR;5A;2\n"
    )
    informe = SVC.import_lessons(demo, texto)
    assert informe.created == ("4",)
    motivo = next(i for i in informe.issues if i.row == 2)
    assert motivo.field == "periods_per_week" and "comparten esta columna" in motivo.message
    assert _numeros(demo) == [4]


def test_un_acople_no_entra_a_medias(demo: UntisSession) -> None:
    """Si falla una línea del acople, la lección entera se queda fuera."""
    texto = "Lección;Materia;Profesor;Clases;Horas/semana\n;MUS;ANA;5A;3\n;MUS;NOEXISTE;5B;\n"
    informe = SVC.import_lessons(demo, texto)
    assert informe.created == ("1",)  # la primera fila es una lección suya, no el acople
    assert len(demo.project.lessons) == 1

    otra = _demo()
    acople = "Lección;Materia;Profesor;Clases;Horas/semana\nL;MUS;ANA;5A;3\nL;MUS;NOEXISTE;5B;\n"
    informe = SVC.import_lessons(otra, acople)
    assert not informe.applied and not otra.project.lessons


def test_columna_desconocida_se_ignora_y_avisa(demo: UntisSession) -> None:
    texto = (
        "Lección;Materia;Clases;Horas/semana;color\n"
        "20;MAT;5A;4;azul\n"
        "21;FIS;5A;2;rojo\n"
        "20;MUS;5B;;gris\n"
    )
    informe = SVC.import_lessons(demo, texto)
    assert informe.unknown_columns == ("color",)
    assert "Columna desconocida" in informe.summary()
    # Repetir el número no es un error: son dos líneas acopladas de la misma lección.
    assert sorted(_numeros(demo)) == [20, 21]
    assert [x.subject for x in demo.project.lesson_by_number[20].lines] == ["MAT", "MUS"]


def test_un_numero_explicito_no_pisa_a_una_leccion_nueva(demo: UntisSession) -> None:
    """La fila sin número se lleva el 1; la que pide el 1 explícitamente, avisa."""
    informe = SVC.import_lessons(
        demo, "Lección;Materia;Clases;Horas/semana\n;MAT;5A;4\n1;FIS;5A;2\n"
    )
    assert informe.created == ("1",)
    assert "ya se lo ha llevado" in informe.summary()
    assert _numeros(demo) == [1]
    assert demo.project.lesson_by_number[1].lines[0].subject == "MAT"


def test_sin_columna_de_materia_no_se_importa_nada(demo: UntisSession) -> None:
    informe = SVC.import_lessons(demo, "Lección;Clases;Horas/semana\n;5A;4\n")
    assert not informe.applied and "materia" in informe.summary()


def test_estricto_no_aplica_nada_si_algo_falla(demo: UntisSession) -> None:
    texto = "Lección;Materia;Clases;Horas/semana\n;MAT;5A;4\n;NOEXISTE;5A;2\n"
    informe = SVC.import_lessons(demo, texto, strict=True)
    assert not informe.applied and informe.created == ("1",)
    assert not demo.project.lessons


# --------------------------------------------------------------------------- #
# Un solo paso de deshacer
# --------------------------------------------------------------------------- #


def test_una_importacion_entera_es_un_solo_deshacer(demo: UntisSession) -> None:
    antes = demo.project
    filas = "\n".join(f";MAT;ANA;5A;{n % 4 + 1}" for n in range(200))
    informe = SVC.import_lessons(demo, f"Lección;Materia;Profesor;Clases;Horas/semana\n{filas}\n")
    assert informe.applied and len(informe.created) == 200
    assert "200" in demo.undo_label
    assert demo.undo() and demo.project == antes and not demo.project.lessons
    assert demo.redo() and len(demo.project.lessons) == 200


def test_previsualizar_no_toca_nada(demo: UntisSession) -> None:
    antes = demo.project
    previo = preview_lessons(demo, "Lección;Materia;Clases;Horas/semana\n;MAT;5A;4\n")
    assert previo.created == ("1",) and not previo.applied
    assert demo.project is antes and not demo.can_undo


# --------------------------------------------------------------------------- #
# Ida y vuelta con el proyecto real seudonimizado (709 lecciones)
# --------------------------------------------------------------------------- #


def test_exportar_e_importar_las_709_lecciones_no_pierde_nada(anon: UntisSession) -> None:
    sesion = SVC.snapshot(anon)
    assert len(sesion.project.lessons) == 709
    csv = SVC.export_lessons(sesion)
    assert csv.splitlines()[0].startswith("Lección;Materia;Profesor;Clases")
    assert len(csv.splitlines()) == sum(len(le.lines) for le in sesion.project.lessons) + 1

    antes = sesion.project
    informe = SVC.import_lessons(sesion, csv)
    assert informe.ok, informe.summary()
    assert len(informe.unchanged) == 709 and not informe.applied
    assert sesion.project is antes


def test_exportar_en_aleman_y_volver_a_importar(anon: UntisSession) -> None:
    sesion = SVC.snapshot(anon)
    csv = SVC.export_lessons(sesion, language="de", delimiter="\t")
    assert csv.splitlines()[0].startswith("Unterricht\tFach\tLehrer\tKlassen")
    informe = SVC.import_lessons(sesion, csv)
    assert informe.ok and len(informe.unchanged) == 709


def test_los_acoples_reales_se_conservan(anon: UntisSession) -> None:
    sesion = SVC.snapshot(anon)
    acoplada = max(sesion.project.lessons, key=lambda le: len(le.lines))
    assert len(acoplada.lines) > 3
    filas = lesson_rows(sesion, [acoplada.number])
    assert len(filas) == len(acoplada.lines)
    assert {f[0] for f in filas} == {str(acoplada.number)}
    destino = SVC.snapshot(anon)
    destino.project = destino.project.__class__(school=destino.project.school)
    # Sin datos maestros no puede entrar: el informe lo explica en vez de romperse.
    informe = SVC.import_lessons(destino, table_from_rows(LESSON_FIELDS, filas))
    assert not informe.applied and not informe.ok


# --------------------------------------------------------------------------- #
# Interfaz
# --------------------------------------------------------------------------- #


def test_pegar_lineas_crea_un_acople_en_un_deshacer(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, LessonsWindow(bridge))
    w.set_filter("all")
    antes = bridge.session.project
    bloque = "L1\tMUS\tANA\t5A\t\t\t\t\t3\nL1\tMUS\tBEA\t5B\n"
    assert w.paste_text(bloque)
    qapp.processEvents()
    assert len(bridge.session.project.lessons) == 1
    assert len(bridge.session.project.lessons[0].lines) == 2
    assert w.message.kind == "ok" and "1 fila(s) nueva(s)" in w.message.text()
    assert bridge.undo() and bridge.session.project == antes


def test_copiar_y_volver_a_pegar_la_leccion_actual(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    assert SVC.import_lessons(
        bridge.session, "Lección;Materia;Profesor;Clases;Horas/semana\n5;MAT;ANA;5A;4\n"
    ).applied
    w = _make(qtbot, LessonsWindow(bridge))
    w.set_filter("all")
    w.select_lesson(5)
    texto = w.copy_selection()
    assert texto.startswith("5\tMAT\tANA\t5A") and QGuiApplication.clipboard().text() == texto
    antes = bridge.session.project
    assert w.paste_clipboard()  # la misma lección: no cambia nada
    qapp.processEvents()
    assert bridge.session.project is antes


def test_importar_un_csv_de_lecciones_desde_un_archivo(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication, tmp_path: Path
) -> None:
    w = _make(qtbot, LessonsWindow(bridge))
    w.set_filter("all")
    ruta = tmp_path / "lecciones.csv"
    ruta.write_text(
        "Lección,Materia,Profesor,Clases,Horas/semana\n,MAT,ANA,5A,4\n,NOEXISTE,BEA,5B,2\n",
        encoding="utf-8",
    )
    informe = w.import_csv(ruta)
    qapp.processEvents()
    assert informe is not None and informe.created == ("1",) and informe.rows_failed == 1
    assert w.message.kind == "warning" and "NOEXISTE" in w.message.text()
    assert w.model.row_of(1) >= 0


def test_exportar_csv_desde_la_ventana_y_volver_a_cargarlo(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication, tmp_path: Path
) -> None:
    SVC.import_lessons(
        bridge.session,
        "Lección;Materia;Profesor;Clases;Horas/semana\n;MAT;ANA;5A;4\n;FIS;BEA;5B;2\n",
    )
    w = _make(qtbot, LessonsWindow(bridge))
    w.refresh()
    destino = w.export_csv(tmp_path / "lecciones")
    assert destino is not None and destino.name == "lecciones.csv"
    assert destino.read_bytes().startswith(b"\xef\xbb\xbf")
    assert w.message.kind == "ok" and "2 lección(es)" in w.message.text()

    antes = bridge.session.project.lessons
    bridge.attach(_demo())
    qapp.processEvents()
    otra = _make(qtbot, LessonsWindow(bridge))
    informe = otra.import_csv(destino)
    assert informe is not None and informe.ok
    assert bridge.session.project.lessons == antes


def test_los_botones_nuevos_llevan_icono_y_ayuda(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, LessonsWindow(bridge))
    w.set_filter("all")
    for boton in (w.copy_button, w.paste_button, w.import_button, w.export_button):
        assert not boton.icon().isNull()
        assert len(boton.toolTip()) > 20 and boton.text()
    assert w.import_button.isEnabled() and not w.export_button.isEnabled()
    SVC.import_lessons(bridge.session, "Lección;Materia;Clases;Horas/semana\n;MAT;5A;4\n")
    w.refresh()
    assert w.export_button.isEnabled() and w.copy_button.isEnabled()

    sin_proyecto = _make(qtbot, LessonsWindow(FacadeBridge(SVC)))
    assert not sin_proyecto.import_button.isEnabled()
    assert sin_proyecto.import_csv("x.csv") is None
    assert sin_proyecto.export_csv("x.csv") is None
    assert sin_proyecto.copy_selection() == ""
