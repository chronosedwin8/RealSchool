"""Usabilidad de las ventanas de escritorio (headless).

Comprueba lo que hace la aplicación comprensible e independiente:

- Rejillas de tiempo: se crean, copian, renombran, borran, amplían y regeneran
  desde la propia ventana (sin ninguna otra herramienta).
- Cada botón y cada acción llevan icono y una ayuda emergente que explica qué
  hacen (no solo repiten el texto).
- Datos maestros: Añadir visible y texto de ayuda con la tabla vacía.
- Ponderación: Restablecer valores por defecto.
- Optimización: Iniciar desactivado, con el motivo, si no hay lecciones.
- Evaluación: número con separador de miles e icono de estado.
- Diagnóstico: grupos con nombres legibles y sin "Sin proyecto" con uno abierto.
- Planificación y Horarios: texto legible sobre cualquier color de materia.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt, QTime
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QTabBar,
    QToolBar,
    QWidget,
)
from pytestqt.qtbot import QtBot

import untis_desktop.windows.master_data  # registra las ventanas de datos maestros
from scheduling_platform.application import MasterKind, UntisService, UntisSession
from untis_desktop.icons import ICONS
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.registry import load_windows, spec
from untis_desktop.theme import fmt_int, text_color_for
from untis_desktop.widgets import master_grid
from untis_desktop.widgets.master_grid import MasterDataGrid
from untis_desktop.widgets.uikit import EXEMPT_PROPERTY
from untis_desktop.windows.diagnosis import DiagnosisPanel
from untis_desktop.windows.evaluation import EvaluationWindow
from untis_desktop.windows.lessons import LessonsWindow
from untis_desktop.windows.optimization import OptimizationWindow
from untis_desktop.windows.planning import PlanningWindow
from untis_desktop.windows.requests import PALETTE, RequestsWindow
from untis_desktop.windows.time_grids import GridDialog, TimeGridsWindow
from untis_desktop.windows.timetables import TimetablesWindow
from untis_desktop.windows.weighting import WeightingWindow

SVC = UntisService()

#: Ventanas de este paquete de trabajo (las del inicio y la cinta son de otro).
MY_KEYS = (
    *(clave for clave, *_ in untis_desktop.windows.master_data.MASTER_WINDOWS),
    "time_grids",
    "requests",
    "lessons",
    "weighting",
    "settings",
    "optimization",
    "evaluation",
    "diagnosis",
    "planning",
    "timetables",
)

#: Botones internos de Qt que no son órdenes del usuario (esquina de tabla,
#: botón de borrar del filtro, flechas de desplazamiento de pestañas, »).
QT_INTERNAL_BUTTONS = frozenset({"QTableCornerButton", "QLineEditIconButton", "QToolBarExtension"})


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _layout_aislado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ini = str(tmp_path / "layout.ini")
    monkeypatch.setattr(
        master_grid, "layout_settings", lambda: QSettings(ini, QSettings.Format.IniFormat)
    )


@pytest.fixture(scope="module")
def anon_session(anon_xml_path: Path) -> UntisSession:
    return SVC.open(anon_xml_path)


@pytest.fixture
def bridge(qapp: QApplication) -> Iterator[FacadeBridge]:
    b = FacadeBridge(SVC)
    yield b
    b.set_language("es")


@pytest.fixture
def anon(bridge: FacadeBridge, anon_session: UntisSession, qapp: QApplication) -> FacadeBridge:
    bridge.attach(SVC.snapshot(anon_session))
    qapp.processEvents()
    return bridge


@pytest.fixture
def empty(bridge: FacadeBridge, qapp: QApplication) -> FacadeBridge:
    """Proyecto nuevo: solo la rejilla Estándar, sin clases ni lecciones."""
    bridge.attach(SVC.new("Colegio Nuevo"))
    qapp.processEvents()
    return bridge


def _make[W: QWidget](qtbot: QtBot, widget: W) -> W:
    qtbot.addWidget(widget)
    return widget


def _flush(qapp: QApplication) -> None:
    qapp.processEvents()
    qapp.processEvents()


def _keys(grid: MasterDataGrid) -> list[str]:
    return [r.key for r in grid.model.rows]


def _grid_view(bridge: FacadeBridge, grid_id: str) -> tuple[int, tuple[bool, ...], tuple[int, ...]]:
    """`(nº de períodos, recreos, días)` de una rejilla según la Fachada."""
    g = next(g for g in SVC.grids(bridge.session) if g.id == grid_id)
    return len(g.periods), tuple(p.is_break for p in g.periods), g.days


# --------------------------------------------------------------------------- #
# Rejillas de tiempo: gestión completa desde la ventana
# --------------------------------------------------------------------------- #


def _fill_new_grid(dialog: QDialog) -> bool:
    assert isinstance(dialog, GridDialog)
    dialog.name_edit.setText("Tarde")
    dialog.day_checks[5].setChecked(False)
    dialog.periods.setValue(5)
    dialog.start.setTime(QTime(15, 0))
    dialog.duration.setValue(50)
    dialog.gap.setValue(10)
    dialog.set_breaks({2: 15})
    # Vista previa en vivo: 5 períodos + 1 recreo, con las horas ya calculadas.
    assert dialog.preview_table.rowCount() == 6
    primera = dialog.preview_table.item(0, 1)
    recreo = dialog.preview_table.item(2, 2)
    assert primera is not None and primera.text() == "15:00 - 15:50"
    assert recreo is not None and recreo.text() == "Recreo"
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    return True


def test_rejillas_nueva_con_el_dialogo(
    qtbot: QtBot, empty: FacadeBridge, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _make(qtbot, TimeGridsWindow(empty))
    assert w.tabs.count() == 1 and w.new_action.isEnabled()
    monkeypatch.setattr(w, "exec_dialog", _fill_new_grid)
    resultado = w.new_grid_dialog()
    assert resultado is not None and resultado.ok, resultado
    _flush(qapp)
    assert w.current_grid_id() == "Tarde" and w.tabs.count() == 2
    n, recreos, dias = _grid_view(empty, "Tarde")
    assert n == 6 and recreos == (False, False, True, False, False, False)
    assert dias == (1, 2, 3, 4)
    pagina = w.page("Tarde")
    inicio = pagina.table.item(0, 0)
    assert inicio is not None and inicio.text() == "15:00"
    assert not pagina.table.verticalHeaderItem(2).icon().isNull()  # recreo con su icono

    # El diálogo no deja aceptar sin nombre y explica por qué.
    dialogo = _make(qtbot, GridDialog(w))
    dialogo.name_edit.setText("")
    assert not dialogo.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert dialogo.problem() and not dialogo.error.isHidden()
    dialogo.name_edit.setText("X")
    dialogo.set_breaks({9: 10})  # recreo fuera de la jornada
    assert "recreo" in dialogo.problem().lower()


def test_rejillas_copiar_renombrar_periodos_dias_y_generar(
    qtbot: QtBot, empty: FacadeBridge, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _make(qtbot, TimeGridsWindow(empty))
    base = w.current_grid_id()
    assert base is not None
    n_base, _recreos, _dias = _grid_view(empty, base)

    monkeypatch.setattr(w, "ask_text", lambda *_args: "Copia")
    resultado = w.copy_dialog()
    assert resultado is not None and resultado.ok
    assert w.current_grid_id() == "Copia" and _grid_view(empty, "Copia")[0] == n_base

    assert w.rename_grid("Rejilla de tarde").ok
    assert w.tabs.tabText(w.tabs.currentIndex()) == "Rejilla de tarde"

    assert w.add_period().ok
    assert _grid_view(empty, "Copia")[0] == n_base + 1
    assert w.page("Copia").table.rowCount() == n_base + 1
    assert w.remove_last_period().ok
    assert _grid_view(empty, "Copia")[0] == n_base

    sabado = w.day_checks[6]
    assert not sabado.isChecked()
    sabado.setChecked(True)  # la casilla edita la rejilla visible
    _flush(qapp)
    assert 6 in _grid_view(empty, "Copia")[2]
    for d in (1, 2, 3, 4, 5, 6):
        w.day_checks[d].setChecked(False)
    _flush(qapp)
    assert not w.message.isHidden()  # sin ningún día: la Fachada lo rechaza y se ve
    assert _grid_view(empty, "Copia")[2] == (6,)

    def generar(dialog: QDialog) -> bool:
        assert isinstance(dialog, GridDialog) and dialog.regenerate
        assert not dialog.name_edit.isEnabled() or dialog.name_edit.isReadOnly()
        dialog.periods.setValue(4)
        dialog.set_breaks({})
        return True

    monkeypatch.setattr(w, "exec_dialog", generar)
    resultado = w.regenerate_dialog()
    assert resultado is not None and resultado.ok
    assert _grid_view(empty, "Copia")[:2] == (4, (False,) * 4)

    monkeypatch.setattr(w, "confirm", lambda *_args: True)
    borrado = w.delete_dialog()
    assert borrado is not None and borrado.ok
    assert "Copia" not in w.pages and w.message.isHidden()


def test_rejillas_borrar_una_en_uso_muestra_el_motivo(
    qtbot: QtBot, anon: FacadeBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _make(qtbot, TimeGridsWindow(anon))
    assert w.select_grid("Bachillerato")
    monkeypatch.setattr(w, "confirm", lambda *_args: True)
    antes = anon.session.project
    resultado = w.delete_dialog()
    assert resultado is not None and not resultado.ok
    assert anon.session.project is antes and "Bachillerato" in w.pages
    assert not w.message.isHidden() and "usan" in w.message.text()


# --------------------------------------------------------------------------- #
# Iconos y ayudas en todas las ventanas
# --------------------------------------------------------------------------- #


def _plain(text: str) -> str:
    return text.replace("&", "").replace("...", "").strip(" .:").casefold()


def _missing_icon_or_help(root: QWidget) -> list[str]:
    """Botones y acciones de `root` sin icono o sin ayuda que explique algo."""
    faltan: list[str] = []
    for boton in root.findChildren(QAbstractButton):
        clase = boton.metaObject().className()
        if clase in QT_INTERNAL_BUTTONS or isinstance(boton.parent(), QTabBar):
            continue
        if boton.property(EXEMPT_PROPERTY):
            continue
        ayuda = boton.toolTip().strip()
        if boton.icon().isNull() or not ayuda or _plain(ayuda) == _plain(boton.text()):
            faltan.append(f"{clase} {boton.text()!r} ayuda={ayuda!r}")
    for accion in root.findChildren(QAction):
        if accion.isSeparator() or accion.objectName().startswith("_q_"):
            continue  # separadores y acciones internas de Qt (p. ej. borrar el filtro)
        padre = accion.parent()
        if isinstance(padre, QToolBar) and accion.isCheckable() and not accion.text():
            continue  # mostrar/ocultar la barra (acción interna de QToolBar)
        if accion.menu() is not None and not accion.text():
            continue  # acción propia de un menú emergente (no se ve como orden)
        ayuda = accion.toolTip().strip()
        if accion.icon().isNull() or not ayuda or _plain(ayuda) == _plain(accion.text()):
            faltan.append(f"QAction {accion.text()!r} ayuda={ayuda!r}")
    return faltan


def test_todos_los_botones_y_acciones_tienen_icono_y_ayuda(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    load_windows()
    anon.select("class", "K7B")
    problemas: dict[str, list[str]] = {}
    for key in MY_KEYS:
        ventana = _make(qtbot, spec(key).factory(anon))
        refrescar = getattr(ventana, "refresh", None)
        if callable(refrescar):
            refrescar()
        _flush(qapp)
        faltan = _missing_icon_or_help(ventana)
        if faltan:
            problemas[key] = faltan
        # Menús que se crean al pedirlos.
        if isinstance(ventana, MasterDataGrid):
            for menu in (ventana.header_menu(), ventana.row_menu()):
                for accion in menu.actions():
                    if accion.isSeparator():
                        continue
                    assert accion.toolTip(), (key, accion.text())
                    if not accion.isCheckable():  # casillas de columna: el tic es el estado
                        assert not accion.icon().isNull(), (key, accion.text())
        if isinstance(ventana, PlanningWindow):
            assert ventana.grid is not None
            celda = ventana.grid.cells[0]
            contextual = ventana.context_menu(celda.day, celda.period)
            assert contextual is not None
            faltan_menu = _missing_icon_or_help(contextual)
            if faltan_menu:
                problemas[f"{key}:menu"] = faltan_menu
    assert not problemas, problemas


def test_cada_ventana_declara_icono_y_ayuda() -> None:
    load_windows()
    for key in MY_KEYS:
        s = spec(key)
        assert s.icon in ICONS, key
        assert len(s.tooltip) > 20 and s.tooltip.endswith("."), key


# --------------------------------------------------------------------------- #
# Datos maestros: Añadir, estado vacío, ayudas de cabecera
# --------------------------------------------------------------------------- #


def test_datos_maestros_anadir_y_estado_vacio(
    qtbot: QtBot, empty: FacadeBridge, qapp: QApplication
) -> None:
    grid = _make(qtbot, MasterDataGrid(empty, MasterKind.CLASSES, "classes"))
    grid.resize(900, 400)
    grid.show()
    qtbot.waitExposed(grid)
    assert grid.model.rows == ()
    assert grid.hint.isVisible() and "Aún no hay clases" in grid.hint.text()
    blanca = grid.blank_index()
    assert "nombre corto" in str(blanca.data(Qt.ItemDataRole.DisplayRole))
    assert blanca.data(Qt.ItemDataRole.EditRole) == ""
    assert not grid.remove_button.isEnabled()  # nada que borrar todavía

    grid.add_button.click()
    assert grid.view.state() == QAbstractItemView.State.EditingState
    assert grid.view.currentIndex() == grid.blank_index()
    grid.view.closePersistentEditor(grid.view.currentIndex())

    assert grid.add_entity("1A")
    _flush(qapp)
    assert _keys(grid) == ["1A"] and grid.current_key() == "1A"
    assert grid.hint.isHidden() and grid.remove_button.isEnabled()
    assert not grid.add_entity("1A")  # repetido: rechazado con el motivo a la vista
    assert not grid.message.isHidden()

    # Un filtro sin resultados también se explica.
    grid.set_filter("zzz")
    assert grid.hint.isVisible() and "zzz" in grid.hint.text()
    grid.set_filter("")

    col = next(i for i, c in enumerate(grid.model.columns) if c.field == "periods_per_day")
    ayuda = str(grid.model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole))
    assert "4-7" in ayuda and "Períodos/día" in ayuda
    assert not grid.columns_button.icon().isNull() and grid.columns_button.menu() is not None


# --------------------------------------------------------------------------- #
# Lecciones y Deseos
# --------------------------------------------------------------------------- #


def test_lecciones_acoples_ayudas_y_barra_de_suma(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, LessonsWindow(anon))
    w.set_filter("class", "K7B")
    acoplada = next(le for le in w.model.lessons if le.is_coupled)
    sub = w.model.row_of(acoplada.number, 1)
    assert w.model.index(sub, 0).data(Qt.ItemDataRole.DecorationRole) is not None
    assert (
        w.model.index(w.model.row_of(acoplada.number), 0).data(Qt.ItemDataRole.DecorationRole)
        is None
    )
    ayudas = [
        str(w.model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole))
        for c in range(w.model.columnCount())
    ]
    assert any("1-2" in a for a in ayudas) and any("mismo día" in a for a in ayudas)
    assert w.sum_icon.property("state") in ("ok", "warning", "error")
    assert w.hint.isHidden()

    w.set_filter("class", "")
    nueva = _make(qtbot, LessonsWindow(anon))
    anon.attach(SVC.new("Vacío"))
    _flush(qapp)
    nueva.set_filter("all")
    assert "Nueva lección" in nueva.hint_text()


def test_deseos_paleta_con_significado_y_leyenda(qtbot: QtBot, anon: FacadeBridge) -> None:
    w = _make(qtbot, RequestsWindow(anon))
    for valor in PALETTE:
        assert w.palette_buttons[valor].toolTip()
    assert "imposible" in w.palette_buttons[-3].toolTip()
    assert "muy deseable" in w.palette_buttons[3].toolTip()
    assert len(w.legend.texts) >= 5
    # Cada botón pinta su propio valor (también el -1, que QButtonGroup reserva).
    for valor in PALETTE:
        w.palette_buttons[valor].click()
        assert w.grid.paint_value == valor


# --------------------------------------------------------------------------- #
# Ponderación, Optimización, Evaluación
# --------------------------------------------------------------------------- #


def test_ponderacion_restablecer_valores_por_defecto(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, WeightingWindow(anon))
    fabrica = w.defaults()
    criterios = list(fabrica)[:3]
    for c in criterios:
        assert w.set_value(c, 0 if fabrica[c] else 4).ok
    _flush(qapp)
    actuales = {s.criterion: s.value for v in SVC.weighting_tabs(anon.session) for s in v.sliders}
    assert any(actuales[c] != fabrica[c] for c in criterios)
    assert w.reset_defaults().ok
    _flush(qapp)
    actuales = {s.criterion: s.value for v in SVC.weighting_tabs(anon.session) for s in v.sliders}
    assert actuales == fabrica
    assert not w.message.isHidden()
    fila = w.sliders[criterios[0]]
    assert "peso" in fila.value.text() and f"({fabrica[criterios[0]]})" in fila.value.text()


def test_optimizacion_sin_lecciones_no_deja_iniciar(
    qtbot: QtBot, empty: FacadeBridge, anon_session: UntisSession, qapp: QApplication
) -> None:
    w = _make(qtbot, OptimizationWindow(empty))
    assert not w.start_button.isEnabled()
    assert not w.reason.isHidden() and "lecciones" in w.reason.text().lower()
    assert not w.start()
    assert w.intro.text()  # la franja que explica el orden A -> B -> E
    empty.attach(SVC.snapshot(anon_session))
    _flush(qapp)
    assert w.start_button.isEnabled() and w.reason.isHidden()


def test_evaluacion_numero_con_miles_e_icono(qtbot: QtBot, anon: FacadeBridge) -> None:
    w = _make(qtbot, EvaluationWindow(anon))
    w.refresh()
    esperado = SVC.evaluation(anon.session)
    assert esperado is not None and esperado.total >= 1000
    assert w.total_label.text() == fmt_int(esperado.total) and "." in w.total_label.text()
    assert w.status_icon.property("state") == ("error" if esperado.clashes else "ok")
    assert w.status_text.text()
    fila = w.timetables_table.item(0, 3)
    assert fila is not None and fila.text() == fmt_int(w.summaries[0].total)


# --------------------------------------------------------------------------- #
# Diagnóstico
# --------------------------------------------------------------------------- #


def test_diagnostico_nombres_legibles_y_sin_estado_viejo(
    qtbot: QtBot, bridge: FacadeBridge, anon_session: UntisSession, qapp: QApplication
) -> None:
    w = _make(qtbot, DiagnosisPanel(bridge))
    assert "Sin proyecto" in w.summary.text()
    bridge.attach(SVC.snapshot(anon_session))
    _flush(qapp)
    assert "Sin proyecto" not in w.summary.text()  # oculto: queda pendiente, no viejo
    w.refresh()
    textos: list[str] = []
    codigos: list[str] = []
    for fila in range(w.model.rowCount()):
        rama = w.model.item(fila, 0)
        assert not rama.icon().isNull()
        for g in range(rama.rowCount()):
            grupo = rama.child(g, 0)
            textos.append(grupo.text())
            codigos.append(str(grupo.data(Qt.ItemDataRole.UserRole)))
            assert grupo.toolTip() and "_" not in grupo.toolTip().split("\n")[0]
    assert "linea_sin_alumnos" in codigos
    assert "Líneas sin clases ni grupo" in textos
    assert all("_" not in t for t in textos), textos
    assert "Doble clic" in w.hint.text()
    cabecera = w.tree.header()
    assert cabecera.sectionResizeMode(0) == cabecera.ResizeMode.Stretch


# --------------------------------------------------------------------------- #
# Planificación y Horarios: texto legible
# --------------------------------------------------------------------------- #


def test_planificacion_texto_legible_ayuda_y_leyenda(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, PlanningWindow(anon))
    assert w.set_focus("class", "K7B")
    assert w.grid is not None
    oscuras = 0
    for c in w.grid.cells:
        item = w.item_at(c.day, c.period)
        assert item is not None
        fondo = item.background().color()
        assert item.foreground().color() == text_color_for(fondo)
        oscuras += text_color_for(fondo).name() == "#ffffff"
        assert f"Lección {c.lesson}" in item.toolTip()
    assert oscuras  # K7B tiene materias con colores oscuros: texto blanco
    assert "Puede ir aquí" in w.legend.texts and "Fijada" in w.legend.texts
    c = w.grid.cells[0]
    w.select_cell(c.day, c.period)
    assert w.unplace_button.isEnabled() and w.open_button.isEnabled()


def test_horarios_texto_legible_y_menu_de_exportar(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, TimetablesWindow(anon))
    w.refresh()
    pane = w.panes[0]
    assert pane.set_entity("class", "K7B")
    assert pane.grid is not None
    for c in pane.grid.cells:
        fila = next(i for i, p in enumerate(pane.grid.periods) if p.number == c.period)
        item = pane.table.item(fila, pane.grid.days.index(c.day))
        assert item is not None
        assert item.foreground().color() == text_color_for(item.background().color())
        assert "Lección" in item.toolTip()
    acciones = [a for a in w.export_menu.actions() if not a.isSeparator()]
    assert len(acciones) == 7
    assert all(not a.icon().isNull() and a.toolTip() != a.text() for a in acciones)
