"""Mover clases arrastrándolas dentro de la ventana Horarios.

El coordinador mira el horario en la ventana Horarios y, como en Untis, espera
poder mover ahí las horas. La máquina de arrastre es la del Diálogo de
planificación (`untis_desktop.widgets.timetable_drag`), así que estas pruebas
ejercitan los mismos métodos públicos que llaman los manejadores de ratón
(`begin_drag`, `hover`, `drop_on`, `end_drag`) sobre el export seudonimizado
real, más un arrastre empezado con el ratón de verdad.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.theme import TARGET_NO_COLOR, TARGET_OK_COLOR
from untis_desktop.widgets.timetable_cells import DELTA_ROLE, MARK_ROLE
from untis_desktop.widgets.timetable_drag import Cell
from untis_desktop.windows.timetables import TimetablePane, TimetablesWindow

# --------------------------------------------------------------------------- #
# Fixtures y ayudas
# --------------------------------------------------------------------------- #


@pytest.fixture
def bridge(qapp: QApplication, anon_xml_path: Path) -> FacadeBridge:
    """Puente con una sesión propia del export real (se puede editar)."""
    b = FacadeBridge()
    b.attach(b.service.open(anon_xml_path))
    return b


def _flush(qapp: QApplication) -> None:
    qapp.processEvents()
    qapp.processEvents()


def _busiest_class(b: FacadeBridge) -> str:
    """La clase con más celdas en el horario activo (buena para arrastrar)."""
    s = b.session
    cuenta = Counter(c for le in s.project.lessons for c in le.classes)
    for clase, _n in cuenta.most_common(10):
        if len(b.service.timetable_grid(s, "class", clase).cells) >= 20:
            return clase
    return cuenta.most_common(1)[0][0]


def _window(qtbot: QtBot, b: FacadeBridge) -> tuple[TimetablesWindow, TimetablePane, str]:
    """Ventana Horarios con el primer panel en la clase más cargada."""
    w = TimetablesWindow(b)
    qtbot.addWidget(w)
    w.refresh()
    clase = _busiest_class(b)
    pane = w.panes[0]
    assert pane.set_entity("class", clase)
    assert pane.grid is not None and pane.grid.entity_id == clase
    return w, pane, clase


def _drag_first_cell(pane: TimetablePane) -> tuple[int, Cell]:
    """Empieza a arrastrar la primera celda no fijada que tenga un destino posible."""
    assert pane.grid is not None
    for c in pane.grid.cells:
        if c.fixed:
            continue
        pane.begin_drag(c.lesson, (c.day, c.period))
        if any(t.feasible and (d, p) != (c.day, c.period) for (d, p), t in pane.targets().items()):
            return c.lesson, (c.day, c.period)
    raise AssertionError("ninguna celda tiene destinos posibles")


def _feasible(pane: TimetablePane, origen: Cell) -> list[Cell]:
    """Destinos posibles que además se ven en la tabla."""
    return [
        k
        for k, t in sorted(pane.targets().items())
        if t.feasible and k != origen and pane.item_at(*k) is not None
    ]


# --------------------------------------------------------------------------- #
# Arrastrar y soltar
# --------------------------------------------------------------------------- #


def test_arrastrar_y_soltar_mueve_la_sesion(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, pane, _clase = _window(qtbot, bridge)
    leccion, origen = _drag_first_cell(pane)
    destino = _feasible(pane, origen)[0]
    antes = bridge.service.evaluation(bridge.session)
    assert antes is not None

    cambios: list[str] = []
    bridge.project_changed.connect(cambios.append)
    resultado = pane.drop_on(*destino)
    assert resultado.ok, resultado.message
    assert cambios and pane.drag is None
    assert pane.lesson_at(*destino) == leccion
    assert pane.lesson_at(*origen) != leccion
    assert pane.cell_color(*destino) != QColor(TARGET_OK_COLOR)  # se quitan los colores

    # Se deshace como cualquier edición (Ctrl+Z pasa por la Fachada).
    assert bridge.undo()
    w.refresh()
    assert pane.lesson_at(*origen) == leccion
    vuelta = bridge.service.evaluation(bridge.session)
    assert vuelta is not None and vuelta.total == antes.total


def test_destinos_en_verde_y_rojo_con_su_motivo(qtbot: QtBot, bridge: FacadeBridge) -> None:
    _w, pane, _clase = _window(qtbot, bridge)
    _leccion, origen = _drag_first_cell(pane)
    objetivos = pane.targets()
    posibles = _feasible(pane, origen)
    assert posibles
    assert pane.cell_color(*posibles[0]) == QColor(TARGET_OK_COLOR)

    imposibles = [k for k, t in objetivos.items() if not t.feasible and pane.item_at(*k)]
    assert imposibles
    k = imposibles[0]
    assert pane.cell_color(*k) == QColor(TARGET_NO_COLOR)
    item = pane.item_at(*k)
    assert item is not None and objetivos[k].reason in item.toolTip()
    origen_item = pane.item_at(*origen)
    assert origen_item is not None and origen_item.data(MARK_ROLE) == "source"

    pane.end_drag()  # Esc: el horario queda como estaba
    assert pane.drag is None
    assert pane.cell_color(*k) != QColor(TARGET_NO_COLOR)
    assert pane.cell_color(*posibles[0]) != QColor(TARGET_OK_COLOR)


def test_delta_al_pasar_por_encima(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, pane, _clase = _window(qtbot, bridge)
    leccion, origen = _drag_first_cell(pane)
    destino = _feasible(pane, origen)[0]
    llamadas: list[int] = []
    original = bridge.service.move_delta

    def contar(*args: object, **kwargs: object) -> int | None:
        llamadas.append(1)
        return original(bridge.session, leccion, origen, destino)

    bridge.service.move_delta = contar  # type: ignore[method-assign]
    delta = pane.hover(*destino)
    assert delta is not None and pane.hover(*destino) == delta
    assert llamadas == [1]  # caché por arrastre: un cálculo por celda
    del bridge.service.move_delta  # vuelve al método de la clase
    assert f"{delta:+d}" in w.delta_label.text()
    item = pane.item_at(*destino)
    assert item is not None and item.data(DELTA_ROLE) == delta
    assert f"{delta:+d}" in item.toolTip()

    antes = bridge.service.evaluation(bridge.session)
    assert antes is not None and pane.drop_on(*destino).ok
    despues = bridge.service.evaluation(bridge.session)
    assert despues is not None and despues.total - antes.total == delta


def test_soltar_en_imposible_no_cambia_nada(qtbot: QtBot, bridge: FacadeBridge) -> None:
    _w, pane, _clase = _window(qtbot, bridge)
    _leccion, _origen = _drag_first_cell(pane)
    imposible = next(k for k, t in pane.targets().items() if not t.feasible)
    proyecto = bridge.session.project
    avisos: list[str] = []
    bridge.status.connect(avisos.append)
    assert pane.hover(*imposible) is None
    resultado = pane.drop_on(*imposible)
    assert not resultado.ok and avisos
    assert bridge.session.project is proyecto
    assert pane.drag is None
    assert not pane.drop_on(*imposible).ok  # sin arrastre no hace nada


def test_esc_cancela_el_arrastre(qtbot: QtBot, bridge: FacadeBridge) -> None:
    _w, pane, _clase = _window(qtbot, bridge)
    _leccion, origen = _drag_first_cell(pane)
    destino = _feasible(pane, origen)[0]
    proyecto = bridge.session.project
    QTest.keyClick(pane.table, Qt.Key.Key_Escape)
    assert pane.drag is None
    assert pane.cell_color(*destino) != QColor(TARGET_OK_COLOR)
    item = pane.item_at(*origen)
    assert item is not None and not item.data(MARK_ROLE)
    assert bridge.session.project is proyecto


def test_hora_cerrada_con_deseo_menos_tres_no_es_destino(
    qtbot: QtBot, bridge: FacadeBridge
) -> None:
    w, pane, clase = _window(qtbot, bridge)
    leccion, origen = _drag_first_cell(pane)
    cerrar = _feasible(pane, origen)[0]
    pane.end_drag()
    resultado = bridge.service.set_blocked(bridge.session, "class", clase, [cerrar], blocked=True)
    assert resultado.ok, resultado.message
    w.refresh()
    assert pane.grid is not None and pane.grid.is_blocked(*cerrar)

    objetivo = pane.begin_drag(leccion, origen)
    assert objetivo
    cerrado = pane.targets()[cerrar]
    assert not cerrado.feasible and "-3" in cerrado.reason
    assert pane.cell_color(*cerrar) == QColor(TARGET_NO_COLOR)
    assert not pane.drop_on(*cerrar).ok


def test_leccion_fijada_no_se_puede_mover(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, pane, _clase = _window(qtbot, bridge)
    leccion, origen = _drag_first_cell(pane)
    destino = _feasible(pane, origen)[0]
    pane.end_drag()
    assert bridge.service.set_fixed(bridge.session, leccion, True).ok
    w.refresh()

    objetivos = pane.begin_drag(leccion, origen)
    assert all(not t.feasible for t in objetivos if (t.day, t.period) != origen)
    assert "fijada" in pane.targets()[destino].reason
    proyecto = bridge.session.project
    assert not pane.drop_on(*destino).ok
    assert bridge.session.project is proyecto


def test_varios_paneles_se_refrescan(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, pane, _clase = _window(qtbot, bridge)
    w.set_pane_count(4)
    w.sync_check.setChecked(False)
    assert len(w.visible_panes()) == 4
    assert pane.grid is not None
    celda = next(c for c in pane.grid.cells if not c.fixed and c.teachers)
    profesor = celda.teachers[0]
    assert w.panes[1].set_entity("teacher", profesor)

    leccion, origen = celda.lesson, (celda.day, celda.period)
    assert pane.begin_drag(leccion, origen)
    destino = _feasible(pane, origen)[0]
    assert pane.drop_on(*destino).ok
    # El panel del profesor (otro panel abierto) ya enseña la clase en su sitio nuevo.
    otro = w.panes[1]
    assert otro.entity_id == profesor
    assert otro.lesson_at(*destino) == leccion
    assert otro.lesson_at(*origen) != leccion
    assert otro.drag is None


def test_sin_sesion_o_con_otro_horario_no_hace_nada(qtbot: QtBot, bridge: FacadeBridge) -> None:
    _w, pane, _clase = _window(qtbot, bridge)
    leccion, origen = _drag_first_cell(pane)
    destino = _feasible(pane, origen)[0]
    pane.end_drag()

    # El panel enseña un horario que no es el activo: no se arrastra nada.
    pane.shown_timetable = "otro-horario"
    assert pane.begin_drag(leccion, origen) == ()
    assert pane.drag is None and not pane.drop_on(*destino).ok
    pane.shown_timetable = bridge.session.active_timetable
    assert pane.begin_drag(leccion, origen)
    pane.end_drag()

    # Sin proyecto abierto tampoco, y sin errores.
    vacio = FacadeBridge()
    w2 = TimetablesWindow(vacio)
    qtbot.addWidget(w2)
    w2.refresh()
    hueco = w2.panes[0]
    assert hueco.begin_drag(1, (1, 1)) == ()
    assert hueco.drag is None
    assert not hueco.drop_on(1, 1).ok
    assert hueco.cell_of(0, 0) is None and hueco.position_of(1, 1) is None


def test_el_raton_empieza_el_arrastre(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    """Pulsar y mover sobre una celda arranca el arrastre (sin el bucle de QDrag)."""
    _w, pane, _clase = _window(qtbot, bridge)
    pane.resize(700, 600)
    pane.show()
    qtbot.waitExposed(pane)
    assert pane.grid is not None
    celda = next(c for c in pane.grid.cells if not c.fixed)
    item = pane.item_at(celda.day, celda.period)
    assert item is not None
    pane.table.scrollToItem(item)
    centro = pane.table.visualItemRect(item).center()
    assert pane.table.cell_at(centro) == (celda.day, celda.period)

    arrastres: list[int] = []
    pane.dragger.run = lambda source=None: arrastres.append(1)  # type: ignore[method-assign]
    QTest.mousePress(
        pane.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro
    )
    lejos = centro + QPoint(0, 4 * QApplication.startDragDistance())
    movimiento = QMouseEvent(
        QEvent.Type.MouseMove,
        lejos,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(pane.table.viewport(), movimiento)
    _flush(qapp)
    assert arrastres == [1]
    assert pane.drag is not None and pane.drag.lesson == celda.lesson
    assert pane.targets()
    pane.end_drag()
