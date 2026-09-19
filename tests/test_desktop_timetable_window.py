"""Horarios en ventana hija: varias a la vez y horas aparcadas en Sin colocar.

El coordinador viene de Untis, donde tiene abiertas al mismo tiempo varias
ventanas pequeñas y flotantes (el horario de una clase, el de un profesor, el
de un aula) y puede sacar una clase del horario para dejarla aparcada al lado y
volver a colocarla luego. Estas pruebas ejercitan los métodos públicos que
llaman los manejadores de ratón (`begin_drag`, `drop_on`, `unplace`...), más el
soltar de verdad sobre la lista Sin colocar, sobre el export seudonimizado.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QDropEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMdiArea
from pytestqt.qtbot import QtBot

from untis_desktop.main_window import START_KEY, MainWindow
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.theme import TARGET_NO_COLOR, TARGET_OK_COLOR
from untis_desktop.widgets.timetable_cells import FIXED_ROLE, MARK_ROLE
from untis_desktop.widgets.timetable_drag import MIME_SESSION, Cell
from untis_desktop.windows.timetable_window import TimetableWindow
from untis_desktop.windows.timetables import TimetablesWindow

# --------------------------------------------------------------------------- #
# Fixtures y ayudas
# --------------------------------------------------------------------------- #


@pytest.fixture
def bridge(qapp: QApplication, anon_xml_path: Path) -> FacadeBridge:
    """Puente con una sesión propia del export real (se puede editar)."""
    b = FacadeBridge()
    b.attach(b.service.open(anon_xml_path))
    return b


@pytest.fixture
def shell(qapp: QApplication, tmp_path: Path, bridge: FacadeBridge) -> MainWindow:
    """Ventana principal con el proyecto abierto y ajustes en un `.ini` propio."""
    ajustes = QSettings(str(tmp_path / "realschool.ini"), QSettings.Format.IniFormat)
    w = MainWindow(bridge, ajustes)
    w.resize(1280, 800)
    w.show()
    qapp.processEvents()
    return w


def _busiest_class(b: FacadeBridge) -> str:
    """La clase con más celdas en el horario activo (buena para arrastrar)."""
    s = b.session
    cuenta = Counter(c for le in s.project.lessons for c in le.classes)
    for clase, _n in cuenta.most_common(10):
        if len(b.service.timetable_grid(s, "class", clase).cells) >= 20:
            return clase
    return cuenta.most_common(1)[0][0]


def _window(
    qtbot: QtBot, b: FacadeBridge, kind: str = "class", entity: str = ""
) -> TimetableWindow:
    """Ventana hija suelta (sin MDI): lo mismo que abre la ventana principal."""
    w = TimetableWindow(b, kind, entity or _busiest_class(b))
    qtbot.addWidget(w)
    return w


def _drag_first_cell(w: TimetableWindow) -> tuple[int, Cell]:
    """Empieza a arrastrar la primera celda no fijada que tenga un destino posible."""
    assert w.grid is not None
    for c in w.grid.cells:
        if c.fixed:
            continue
        w.begin_drag(c.lesson, (c.day, c.period))
        if any(t.feasible and (d, p) != (c.day, c.period) for (d, p), t in w.targets().items()):
            return c.lesson, (c.day, c.period)
    raise AssertionError("ninguna celda tiene destinos posibles")


def _feasible(w: TimetableWindow, origen: Cell | None = None) -> list[Cell]:
    """Destinos posibles del arrastre en curso que además se ven en la tabla."""
    return [
        k
        for k, t in sorted(w.targets().items())
        if t.feasible and k != origen and w.item_at(*k) is not None
    ]


def _drop_on_parking(w: TimetableWindow, lesson: int) -> None:
    """Suelta de verdad la clase arrastrada sobre la lista Sin colocar."""
    datos = QMimeData()
    datos.setData(MIME_SESSION, str(lesson).encode("ascii"))
    evento = QDropEvent(
        QPointF(6.0, 6.0),
        Qt.DropAction.MoveAction,
        datos,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.parking_list.dropEvent(evento)


def _free_cell(w: TimetableWindow) -> Cell:
    """Una celda con clase, no fijada (la primera del horario)."""
    assert w.grid is not None
    celda = next(c for c in w.grid.cells if not c.fixed)
    return (celda.day, celda.period)


# --------------------------------------------------------------------------- #
# Varias ventanas hijas a la vez
# --------------------------------------------------------------------------- #


def test_dos_horarios_a_la_vez_son_dos_subventanas(shell: MainWindow, qapp: QApplication) -> None:
    b = shell.bridge
    clase = _busiest_class(b)
    profesor = b.session.project.teachers[0].id
    antes = len(shell.mdi.subWindowList())

    uno = shell.open_timetable_window("class", clase)
    otro = shell.open_timetable_window("teacher", profesor)
    qapp.processEvents()
    assert uno is not None and otro is not None and uno is not otro
    assert shell.open_timetable_keys() == (("class", clase), ("teacher", profesor))
    assert len(shell.mdi.subWindowList()) == antes + 2
    # Flotan como en Untis, no en pestañas.
    assert shell.mdi.viewMode() == QMdiArea.ViewMode.SubWindowView

    subs = [shell._timetable_subs[("class", clase)], shell._timetable_subs[("teacher", profesor)]]
    titulos = [s.windowTitle() for s in subs]
    assert titulos[0].startswith(clase) and titulos[1].startswith(profesor)
    assert titulos[0] != titulos[1]
    assert all(not s.windowIcon().isNull() for s in subs)  # icono del tipo de entidad

    # Las ventanas registradas no se enteran: `open_keys` sigue siendo suyo.
    assert set(shell.open_keys()) <= {START_KEY}
    shell.tile()
    shell.cascade()
    assert len(shell.mdi.subWindowList()) == antes + 2


def test_abrir_el_mismo_horario_dos_veces_enfoca_el_abierto(
    shell: MainWindow, qapp: QApplication
) -> None:
    clase = _busiest_class(shell.bridge)
    primera = shell.open_timetable_window("class", clase)
    otra = shell.open_timetable_window("teacher", shell.bridge.session.project.teachers[0].id)
    repetida = shell.open_timetable_window("class", clase)
    qapp.processEvents()
    assert repetida is primera and otra is not primera
    assert len(shell.open_timetable_keys()) == 2
    assert shell.mdi.activeSubWindow() is shell._timetable_subs[("class", clase)]


def test_sin_proyecto_o_sin_entidad_no_abre_nada(qapp: QApplication, tmp_path: Path) -> None:
    ajustes = QSettings(str(tmp_path / "vacio.ini"), QSettings.Format.IniFormat)
    w = MainWindow(FacadeBridge(), ajustes)
    avisos: list[str] = []
    w.bridge.status.connect(avisos.append)
    assert w.open_timetable_window("class", "1A") is None
    assert w.open_selected_timetable() is None
    assert avisos and not w.open_timetable_keys()


# --------------------------------------------------------------------------- #
# Mover dentro del horario
# --------------------------------------------------------------------------- #


def test_arrastrar_dentro_del_horario_mueve_la_clase(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = _window(qtbot, bridge)
    leccion, origen = _drag_first_cell(w)
    posibles = _feasible(w, origen)
    assert posibles
    assert w.cell_color(*posibles[0]) == QColor(TARGET_OK_COLOR)
    imposibles = [k for k, t in w.targets().items() if not t.feasible and w.item_at(*k)]
    if imposibles:
        item = w.item_at(*imposibles[0])
        assert w.cell_color(*imposibles[0]) == QColor(TARGET_NO_COLOR)
        assert item is not None and w.targets()[imposibles[0]].reason in item.toolTip()
    marca = w.item_at(*origen)
    assert marca is not None and marca.data(MARK_ROLE) == "source"

    destino = posibles[0]
    antes = bridge.service.evaluation(bridge.session)
    assert antes is not None
    delta = w.hover(*destino)
    assert w.drop_on(*destino).ok
    assert w.lesson_at(*destino) == leccion and w.lesson_at(*origen) != leccion
    assert w.drag is None and w.cell_color(*destino) != QColor(TARGET_OK_COLOR)
    despues = bridge.service.evaluation(bridge.session)
    assert despues is not None and delta is not None
    assert despues.total - antes.total == delta


# --------------------------------------------------------------------------- #
# Sacar la hora fuera del horario y volver a colocarla
# --------------------------------------------------------------------------- #


def test_arrastrar_fuera_del_horario_aparca_la_hora(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = _window(qtbot, bridge)
    dia, periodo = _free_cell(w)
    leccion = w.lesson_at(dia, periodo)
    assert leccion is not None
    antes = dict(w.unplaced_lessons())

    assert w.begin_drag(leccion, (dia, periodo))
    _drop_on_parking(w, leccion)
    assert w.drag is None
    assert w.lesson_at(dia, periodo) != leccion
    despues = dict(w.unplaced_lessons())
    assert despues.get(leccion, 0) == antes.get(leccion, 0) + 1
    aparcada = next(
        w.parking_list.item(i)
        for i in range(w.parking_list.count())
        if w.parking_list.item(i).data(Qt.ItemDataRole.UserRole) == leccion
    )
    assert str(leccion) in aparcada.text() and aparcada.toolTip()


def test_de_la_lista_a_una_hora_valida_la_coloca(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = _window(qtbot, bridge)
    dia, periodo = _free_cell(w)
    leccion = w.lesson_at(dia, periodo)
    assert leccion is not None
    antes = dict(w.unplaced_lessons())
    assert w.unplace(dia, periodo).ok
    assert dict(w.unplaced_lessons()).get(leccion, 0) == antes.get(leccion, 0) + 1

    objetivos = w.begin_drag(leccion, None)
    assert objetivos and w.drag is not None and w.drag.source is None
    destino = _feasible(w)[0]
    assert w.drop_on(*destino).ok
    assert w.lesson_at(*destino) == leccion
    assert dict(w.unplaced_lessons()).get(leccion, 0) == antes.get(leccion, 0)


def test_de_la_lista_a_una_hora_imposible_no_hace_nada(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = _window(qtbot, bridge)
    dia, periodo = _free_cell(w)
    leccion = w.lesson_at(dia, periodo)
    assert leccion is not None
    assert w.unplace(dia, periodo).ok

    w.begin_drag(leccion, None)
    imposible = next((k for k, t in w.targets().items() if not t.feasible), None)
    if imposible is None:  # horario muy vacío: se cierra una hora para forzarlo
        w.end_drag()
        cerrar = _feasible(w, None)[0] if w.targets() else (dia, periodo)
        assert bridge.service.set_blocked(
            bridge.session, w.kind, w.entity_id, [cerrar], blocked=True
        ).ok
        w.refresh(force=True)
        w.begin_drag(leccion, None)
        imposible = cerrar
    proyecto = bridge.session.project
    avisos: list[str] = []
    bridge.status.connect(avisos.append)
    assert w.hover(*imposible) is None
    assert not w.drop_on(*imposible).ok
    assert avisos and bridge.session.project is proyecto
    assert dict(w.unplaced_lessons()).get(leccion, 0) >= 1  # sigue aparcada


# --------------------------------------------------------------------------- #
# Menú contextual, F7 y deshacer
# --------------------------------------------------------------------------- #


def test_menu_contextual_fija_y_desfija(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = _window(qtbot, bridge)
    dia, periodo = _free_cell(w)
    menu = w.context_menu(dia, periodo)
    assert menu is not None
    textos = [a.text() for a in menu.actions() if a.text()]
    assert "Fijar" in textos and "Desprogramar (F7)" in textos
    assert any(t.startswith("Abrir lección") for t in textos)
    assert all(
        not a.icon().isNull() and a.toolTip() and a.toolTip() != a.text()
        for a in menu.actions()
        if not a.isSeparator()
    )
    assert w.context_menu(99, 99) is None  # celda vacía o fuera: sin menú

    assert w.toggle_fixed(dia, periodo).ok
    item = w.item_at(dia, periodo)
    assert item is not None and item.data(FIXED_ROLE)
    assert not w.unplace(dia, periodo).ok  # fijada: no se aparca
    vuelta = w.context_menu(dia, periodo)
    assert vuelta is not None and "Desfijar" in [a.text() for a in vuelta.actions()]
    assert w.toggle_fixed(dia, periodo).ok
    item = w.item_at(dia, periodo)
    assert item is not None and not item.data(FIXED_ROLE)

    with qtbot.waitSignal(bridge.lesson_selected, timeout=1000) as elegida:
        w.open_lesson(dia, periodo)
    assert elegida.args == [w.lesson_at(dia, periodo)]


def test_f7_desprograma_la_celda_elegida(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = _window(qtbot, bridge)
    dia, periodo = _free_cell(w)
    leccion = w.lesson_at(dia, periodo)
    assert leccion is not None
    antes = dict(w.unplaced_lessons())
    w.select_cell(dia, periodo)
    w.table.setFocus()
    QTest.keyClick(w.table, Qt.Key.Key_F7)
    assert dict(w.unplaced_lessons()).get(leccion, 0) == antes.get(leccion, 0) + 1
    assert w.lesson_at(dia, periodo) != leccion


def test_ctrl_z_deshace_mover_aparcar_y_fijar(shell: MainWindow, qapp: QApplication) -> None:
    b = shell.bridge
    clase = _busiest_class(b)
    w = shell.open_timetable_window("class", clase)
    assert w is not None
    deshacer = shell._actions["undo"]
    assert deshacer.shortcut() == QKeySequence(QKeySequence.StandardKey.Undo)
    assert "Ctrl+Z" in deshacer.shortcut().toString()

    leccion, origen = _drag_first_cell(w)
    destino = _feasible(w, origen)[0]
    assert w.drop_on(*destino).ok
    deshacer.trigger()
    qapp.processEvents()
    assert w.lesson_at(*origen) == leccion

    antes = dict(w.unplaced_lessons())
    assert w.unplace(*origen).ok
    assert dict(w.unplaced_lessons()) != antes
    deshacer.trigger()
    qapp.processEvents()
    assert dict(w.unplaced_lessons()) == antes
    assert w.lesson_at(*origen) == leccion

    assert w.toggle_fixed(*origen).ok
    deshacer.trigger()
    qapp.processEvents()
    item = w.item_at(*origen)
    assert item is not None and not item.data(FIXED_ROLE)


# --------------------------------------------------------------------------- #
# Abrir desde la cinta y desde la ventana Horarios
# --------------------------------------------------------------------------- #


def test_la_cinta_abre_el_horario_de_lo_seleccionado(shell: MainWindow, qapp: QApplication) -> None:
    accion = shell._actions["timetable_window"]
    assert not accion.icon().isNull()
    assert accion.text() in accion.toolTip() and len(accion.statusTip()) > 20
    assert accion in shell.ribbon_actions()

    avisos: list[str] = []
    shell.bridge.status.connect(avisos.append)
    assert shell.open_selected_timetable() is None  # sin selección: se dice y ya
    assert avisos and "Elige" in avisos[-1]

    clase = _busiest_class(shell.bridge)
    shell.bridge.select("class", clase)
    accion.trigger()
    qapp.processEvents()
    assert shell.open_timetable_keys() == (("class", clase),)
    ventana = shell.timetable_window("class", clase)
    assert ventana is not None and ventana.entity_id == clase


def test_el_boton_del_panel_de_horarios_abre_la_ventana(
    shell: MainWindow, qapp: QApplication
) -> None:
    horarios = shell.show_window("timetables")
    assert isinstance(horarios, TimetablesWindow)
    qapp.processEvents()
    panel = horarios.panes[0]
    clase = _busiest_class(shell.bridge)
    assert panel.set_entity("class", clase)
    assert not panel.window_button.icon().isNull()
    ayuda = panel.window_button.toolTip()
    assert ayuda and ayuda != panel.window_button.text()

    panel.window_button.click()
    qapp.processEvents()
    assert shell.open_timetable_keys() == (("class", clase),)


# --------------------------------------------------------------------------- #
# Cerrar sin dejar basura
# --------------------------------------------------------------------------- #


def test_cerrar_la_ventana_hija_no_deja_basura(shell: MainWindow, qapp: QApplication) -> None:
    clase = _busiest_class(shell.bridge)
    subventanas = len(shell.mdi.subWindowList())
    claves = shell.open_keys()
    assert shell.open_timetable_window("class", clase) is not None
    sub = shell._timetable_subs[("class", clase)]

    sub.close()
    qapp.processEvents()
    qapp.processEvents()
    assert shell.open_timetable_keys() == ()
    assert not shell._timetable_subs
    assert len(shell.mdi.subWindowList()) == subventanas
    assert shell.open_keys() == claves
    assert shell.timetable_window("class", clase) is None
    # Se puede volver a abrir sin arrastrar nada de la anterior.
    otra = shell.open_timetable_window("class", clase)
    assert otra is not None and otra.grid is not None


def test_cerrar_la_ultima_ventana_lleva_a_inicio(shell: MainWindow, qapp: QApplication) -> None:
    clase = _busiest_class(shell.bridge)
    assert shell.open_timetable_window("class", clase) is not None
    shell._subwindows[START_KEY].close()
    qapp.processEvents()
    qapp.processEvents()
    assert shell.open_keys() == ()  # la hija sola no devuelve a Inicio
    assert shell.open_timetable_keys() == (("class", clase),)

    shell._timetable_subs[("class", clase)].close()
    qapp.processEvents()
    qapp.processEvents()
    assert shell.open_keys() == (START_KEY,)


def test_cambiar_de_idioma_renombra_las_ventanas_hijas(
    shell: MainWindow, qapp: QApplication
) -> None:
    clase = _busiest_class(shell.bridge)
    ventana = shell.open_timetable_window("class", clase)
    assert ventana is not None
    sub = shell._timetable_subs[("class", clase)]
    shell.bridge.set_language("de")
    qapp.processEvents()
    assert sub.windowTitle() == ventana.window_title()
    assert ventana.kind_name()  # el tipo se dice en el idioma activo
    shell.bridge.set_language("es")
    qapp.processEvents()
    assert sub.windowTitle().startswith(clase)
