"""Primeros pasos en la UI: página de Inicio, asistente, cinta con iconos y ayuda.

Comprueba que quien abre RealSchool por primera vez tiene un camino guiado: la
página de Inicio con tarjetas y proyectos recientes, el asistente «Crear un
colegio nuevo», la lista de pasos con su estado real, la cinta con icono y
descripción en cada orden, F1, la barra de estado y la disposición guardada.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QTime
from PySide6.QtWidgets import QApplication, QWizard

from scheduling_platform.application import DEFAULT_GRID_ID, MasterKind, OptimizeRequest
from untis_desktop.help import GUIDE_KEY, help_entry, help_html
from untis_desktop.main_window import START_KEY, MainWindow
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.registry import load_windows
from untis_desktop.theme import fmt_int
from untis_desktop.widgets.checklist import ChecklistWidget, StepState
from untis_desktop.widgets.wizard import NewSchoolWizard
from untis_desktop.windows.start import EXAMPLE_PATH

# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    """Ajustes en un `.ini` temporal: nunca se toca el registro del usuario."""
    return QSettings(str(tmp_path / "realschool.ini"), QSettings.Format.IniFormat)


def _pump(qapp: QApplication) -> None:
    for _ in range(3):
        qapp.processEvents()


def _window(qapp: QApplication, settings: QSettings, *, resize: bool = True) -> MainWindow:
    w = MainWindow(FacadeBridge(), settings)
    if resize:
        w.resize(1280, 800)
    w.show()
    _pump(qapp)
    return w


def _next_key(lista: ChecklistWidget) -> str:
    paso = lista.next_step()
    return paso.key if paso is not None else ""


def _wizard_project(bridge: FacadeBridge, classes: str = "6A, 6B") -> NewSchoolWizard:
    """Colegio pequeño creado con el asistente (sin clics)."""
    wz = NewSchoolWizard(bridge)
    wz.school.name_edit.setText("Colegio Prueba")
    wz.people.classes_edit.setPlainText(classes)
    wz.people.teachers_edit.setPlainText("ANA, LUIS")
    wz.people.subjects_edit.setPlainText("MAT")
    wz.accept()
    return wz


# --------------------------------------------------------------------------- #
# Página de Inicio
# --------------------------------------------------------------------------- #


def test_inicio_sin_proyecto_y_tras_nuevo(qapp: QApplication, settings: QSettings) -> None:
    w = _window(qapp, settings)
    assert w.open_keys() == (START_KEY,)
    assert w.active_window_key() == START_KEY
    pagina = w.start_page()
    assert pagina.isVisible()
    assert pagina.cards["example"].isVisibleTo(pagina) == EXAMPLE_PATH.is_file()
    estados = pagina.checklist.statuses()
    assert set(estados.values()) == {StepState.PENDING}
    assert not any(b.isEnabled() for bs in pagina.checklist.buttons.values() for b in bs)
    # Sin proyecto, las ventanas de la cinta (salvo Inicio) no se pueden abrir.
    assert not w._actions["window:lessons"].isEnabled()
    assert w._actions[f"window:{START_KEY}"].isEnabled()
    assert not w._actions["save"].isEnabled()

    w.bridge.new("Colegio Nuevo")
    _pump(qapp)
    assert START_KEY in w.open_keys()
    assert pagina.checklist.statuses()["grid"] is StepState.DONE  # rejilla «Estándar»
    assert "Colegio Nuevo" in pagina.project_badge.text()
    assert w._actions["window:lessons"].isEnabled()


def test_inicio_reaparece_al_cerrar_todo(qapp: QApplication, settings: QSettings) -> None:
    w = _window(qapp, settings)
    w.bridge.new("X")
    w.show_window("lessons")
    w._subwindows[START_KEY].close()
    _pump(qapp)
    assert w.open_keys() == ("lessons",)
    w._subwindows["lessons"].close()
    _pump(qapp)
    assert w.open_keys() == (START_KEY,)


def test_tarjeta_crear_abre_el_asistente(qapp: QApplication, settings: QSettings) -> None:
    w = _window(qapp, settings)
    w.start_page().cards["new"].click()
    _pump(qapp)
    assert isinstance(w.wizard, NewSchoolWizard) and w.wizard.isVisible()
    w.wizard.reject()


def test_recientes_persisten(
    qapp: QApplication, settings: QSettings, anon_xml_path: Path, tmp_path: Path
) -> None:
    w = _window(qapp, settings)
    assert w.recent_files() == []
    assert w.start_page().recent_empty.isVisibleTo(w.start_page())
    assert w.open_path(anon_xml_path)
    anon = str(anon_xml_path.resolve())
    assert w.recent_files() == [anon]
    assert w.start_page().recent_paths() == [anon]

    # Guardar también cuenta como reciente, y va el primero.
    w.bridge.save(tmp_path / "colegio.rsp")
    w.save()
    guardado = str((tmp_path / "colegio.rsp").resolve())
    assert w.recent_files() == [guardado, anon]

    # Se leen en otra ventana (otro arranque) y se descartan los que ya no existen.
    settings.setValue("recent_files", [guardado, str(tmp_path / "borrado.rsp"), anon])
    otra = _window(qapp, settings)
    assert otra.start_page().recent_paths() == [guardado, anon]

    # Como máximo ocho.
    for i in range(10):
        f = tmp_path / f"p{i}.rsp"
        f.write_bytes(b"")
        otra.remember(f)
    assert len(otra.recent_files()) == 8
    assert otra.recent_files()[0] == str((tmp_path / "p9.rsp").resolve())


# --------------------------------------------------------------------------- #
# Asistente
# --------------------------------------------------------------------------- #


def test_asistente_de_punta_a_punta(qapp: QApplication) -> None:
    b = FacadeBridge()
    wz = NewSchoolWizard(b)
    wz.show()
    wz.school.name_edit.setText("Colegio Los Pinos")
    wz.week.day_checks[5].setChecked(False)
    wz.week.day_checks[6].setChecked(True)
    d = wz.day
    d.start_edit.setTime(QTime(8, 30))
    d.duration_spin.setValue(50)
    d.gap_spin.setValue(5)
    d.periods_spin.setValue(6)
    d.clear_breaks()
    d.add_break(2, 15)
    d.add_break(4, 25)
    assert d.preview.rowCount() == 8
    wz.people.classes_edit.setPlainText("6A, 6B\n7A, 6A")
    wz.people.teachers_edit.setPlainText("ANA; LUIS")
    wz.people.subjects_edit.setPlainText("MAT")
    assert "Colegio Los Pinos" in wz.summary_html()

    wz.accept()
    assert wz.result() == QWizard.DialogCode.Accepted
    s = b.session
    p = s.project
    assert p.school.name == "Colegio Los Pinos"
    assert p.school.school_year_begin.endswith("0901")
    (rejilla,) = b.service.grids(s)
    assert rejilla.id == DEFAULT_GRID_ID
    assert rejilla.days == (1, 2, 3, 4, 6)
    assert [x.is_break for x in rejilla.periods] == [
        False, False, True, False, False, True, False, False,
    ]  # fmt: skip
    assert sum(not x.is_break for x in rejilla.periods) == 6
    assert rejilla.periods[0].start == "08:30"
    assert (rejilla.periods[2].start, rejilla.periods[2].end) == ("10:20", "10:35")
    assert rejilla.periods[-1].end == "14:45"
    assert [c.id for c in p.classes] == ["6A", "6B", "7A"]
    assert [t.id for t in p.teachers] == ["ANA", "LUIS"]
    assert [x.id for x in p.subjects] == ["MAT"]
    assert wz.problems == []


def test_asistente_rechaza_datos_no_validos(qapp: QApplication) -> None:
    b = FacadeBridge()
    wz = NewSchoolWizard(b)
    wz.show()
    # Sin nombre: no se crea nada y el motivo se ve en la página.
    wz.accept()
    assert not b.has_session and wz.isVisible()
    assert wz.school.message.isVisibleTo(wz.school)
    assert "nombre" in wz.school.message.text()

    wz.school.name_edit.setText("X")
    for casilla in wz.week.day_checks.values():
        casilla.setChecked(False)
    assert not wz.week.validatePage()
    assert wz.week.message.isVisibleTo(wz.week)
    wz.week.day_checks[1].setChecked(True)

    # Una jornada que acaba después de medianoche se avisa en vivo.
    wz.day.start_edit.setTime(QTime(22, 0))
    wz.day.periods_spin.setValue(8)
    assert "medianoche" in wz.day.message.text()
    assert wz.day.message.isVisibleTo(wz.day)
    wz.accept()
    assert not b.has_session
    assert wz.currentPage() is wz.day

    # Un recreo al final de la jornada no está entre dos clases.
    wz.day.start_edit.setTime(QTime(8, 0))
    wz.day.clear_breaks()
    wz.day.add_break(8, 20)
    assert "no cabe" in wz.day.problem()
    wz.day.clear_breaks()
    assert wz.day.problem() == ""
    wz.accept()
    assert b.session.project.school.name == "X"  # `session` falla si no hay proyecto


# --------------------------------------------------------------------------- #
# Primeros pasos
# --------------------------------------------------------------------------- #


def test_checklist_sigue_los_datos(qapp: QApplication) -> None:
    b = FacadeBridge()
    b.new("X")
    lista = ChecklistWidget(b)
    e = lista.statuses()
    assert e["grid"] is StepState.DONE
    assert e["master"] is StepState.PENDING and e["lessons"] is StepState.PENDING
    assert e["requests"] is StepState.OPTIONAL and e["generate"] is StepState.PENDING
    assert _next_key(lista) == "master"

    svc = b.service
    for tipo, ident in (
        (MasterKind.CLASSES, "5A"),
        (MasterKind.TEACHERS, "ANA"),
        (MasterKind.SUBJECTS, "MAT"),
    ):
        assert b.edit(partial(svc.add_master, b.session, tipo, ident)).ok
    lista.refresh()
    assert lista.statuses()["master"] is StepState.DONE
    assert lista.statuses()["lessons"] is StepState.PENDING
    assert b.edit(
        lambda: svc.add_lesson(b.session, subject="MAT", teacher="ANA", classes=("5A",), periods=3)
    ).ok
    lista.refresh()
    assert lista.statuses()["lessons"] is StepState.DONE
    assert _next_key(lista) == "generate"


def test_checklist_generar_tras_optimizar(qapp: QApplication) -> None:
    b = FacadeBridge()
    _wizard_project(b)
    svc = b.service
    for clase in ("6A", "6B"):
        alta = partial(
            svc.add_lesson, b.session, subject="MAT", teacher="ANA", classes=(clase,), periods=4
        )
        assert b.edit(alta).ok
    lista = ChecklistWidget(b)
    assert lista.statuses()["generate"] is StepState.PENDING
    out = b.run_optimize_sync(OptimizeRequest(strategy="A", time_limit=3))
    assert out.ok, out.message
    lista.refresh()
    e = lista.statuses()
    assert e["generate"] is StepState.DONE
    assert e["review"] is StepState.DONE  # 0 sin colocar, 0 choques
    assert e["output"] is StepState.READY
    assert _next_key(lista) == ""


def test_botones_de_la_checklist_abren_su_ventana(qapp: QApplication, settings: QSettings) -> None:
    w = _window(qapp, settings)
    w.bridge.new("X")
    _pump(qapp)
    lista = w.start_page().checklist
    abiertas = 0
    for paso in lista.steps:
        for clave, boton in zip(paso.windows, lista.buttons[paso.key], strict=True):
            assert boton.isEnabled()
            boton.click()
            _pump(qapp)
            if clave in w._docks:
                assert w._docks[clave].isVisible()
            else:
                assert w.mdi.currentSubWindow() is w._subwindows[clave]
                assert w.active_window_key() == clave
            abiertas += 1
            # Tras abrir una ventana la lista se rehace: se vuelve a leer.
            lista = w.start_page().checklist
    assert abiertas >= 12


# --------------------------------------------------------------------------- #
# Cinta, atajos y ayuda
# --------------------------------------------------------------------------- #


def test_cinta_con_iconos_y_descripciones(qapp: QApplication, settings: QSettings) -> None:
    w = _window(qapp, settings)
    acciones = w.ribbon_actions()
    assert len(acciones) >= len(load_windows()) + 10
    for accion in acciones:
        assert not accion.icon().isNull(), accion.text()
        assert accion.toolTip().strip() and accion.text() in accion.toolTip(), accion.text()
    ventanas = {a.text() for a in acciones}
    assert {s.label("es") for s in load_windows()} <= ventanas
    # Atajos visibles en la descripción.
    assert "Ctrl+1" in w._actions["window:time_grids"].toolTip()
    assert w._actions["window:time_grids"].shortcut().toString() == "Ctrl+1"
    assert "F1" in w._actions["help"].toolTip()
    # Iconos también en las pestañas MDI.
    w.bridge.new("X")
    w.show_window("lessons")
    assert not w._subwindows["lessons"].windowIcon().isNull()
    # Tras cambiar de idioma la cinta se rehace sin atajos duplicados.
    w.bridge.set_language("de")
    w.bridge.set_language("es")
    atajos = [a.shortcut().toString() for a in w.actions() if not a.shortcut().isEmpty()]
    assert len(atajos) == len(set(atajos))


def test_deshacer_dice_que_deshace(qapp: QApplication, settings: QSettings) -> None:
    w = _window(qapp, settings)
    w.bridge.new("X")
    w.bridge.edit(lambda: w.bridge.service.add_master(w.bridge.session, MasterKind.CLASSES, "5A"))
    assert "Deshacer: Añadir 5A" in w._actions["undo"].toolTip()
    assert w._actions["undo"].isEnabled()
    w.bridge.undo()
    assert "Rehacer: Añadir 5A" in w._actions["redo"].toolTip()


def test_f1_ayuda_de_la_ventana_activa(qapp: QApplication, settings: QSettings) -> None:
    for spec in load_windows():
        ficha = help_entry(spec.key)
        assert ficha is not None, spec.key
        assert ficha.summary and 3 <= len(ficha.steps) <= 5, spec.key
        assert ficha.title in help_html(spec.key)
    assert help_entry(GUIDE_KEY) is not None

    w = _window(qapp, settings)
    w.bridge.new("X")
    w.show_window("lessons")
    w._actions["help"].trigger()
    assert w.help_dialog is not None and w.help_dialog.isVisible()
    assert w.help_dialog.current_key == "lessons"
    assert "Lecciones" in w.help_dialog.text.toPlainText()
    w.show_window("time_grids")
    w._actions["help"].trigger()
    assert w.help_dialog.current_key == "time_grids"
    w._actions["guide"].trigger()
    assert w.help_dialog.current_key == GUIDE_KEY
    w.help_dialog.close()


# --------------------------------------------------------------------------- #
# Paneles, disposición y barra de estado
# --------------------------------------------------------------------------- #


def test_registro_oculto_y_disposicion_restaurada(qapp: QApplication, settings: QSettings) -> None:
    w = _window(qapp, settings)
    assert not w._docks["log"].isVisible()
    assert w._docks["diagnosis"].isVisible()
    assert w._docks["diagnosis"].width() >= 300
    registro = w._actions["log"]
    assert not registro.icon().isNull() and registro.isCheckable()
    registro.trigger()
    _pump(qapp)
    assert w._docks["log"].isVisible()
    w.resize(760, 560)  # dentro de la pantalla virtual (800x600)
    _pump(qapp)
    esperado = (w.width(), w.height())
    assert esperado != (1280, 800)
    w.save_layout()

    otra = _window(qapp, settings, resize=False)
    assert otra._docks["log"].isVisible()
    assert (otra.width(), otra.height()) == esperado


def test_barra_de_estado(qapp: QApplication, settings: QSettings, anon_xml_path: Path) -> None:
    w = _window(qapp, settings)
    assert not w.eval_button.isVisibleTo(w)
    w.bridge.new("X")
    _pump(qapp)
    assert w.eval_button.text() == "Sin horario"
    assert w.dirty_label.text() == ""

    w.open_path(anon_xml_path)
    _pump(qapp)
    ev = w.bridge.service.evaluation(w.bridge.session)
    assert ev is not None
    assert fmt_int(ev.total) in w.eval_button.text() and "." in w.eval_button.text()
    assert w.unplaced_button.text().endswith(str(ev.unplaced_periods))
    assert w.clashes_button.text().endswith(str(ev.clashes))
    assert w.clashes_button.isVisibleTo(w)
    w.eval_button.click()
    assert w.active_window_key() == "evaluation"

    w.bridge.edit(lambda: w.bridge.service.add_master(w.bridge.session, MasterKind.ROOMS, "NUEVA"))
    assert w.dirty_label.text() == "Sin guardar"
