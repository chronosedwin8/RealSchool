"""Ventanas de datos de la UI de escritorio (R4) en modo headless.

Datos maestros (`MasterDataGrid`), Rejillas de tiempo, Deseos de tiempo,
Lecciones, Ponderación y Datos del colegio: se construyen con y sin proyecto,
editan a través del puente (deshacer + refresco diferido) y se sincronizan por
la selección. El proyecto real seudonimizado se abre una vez por módulo y cada
prueba que edita trabaja sobre su propia instantánea de sesión.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QWidget
from pytestqt.qtbot import QtBot

import untis_desktop.windows.lessons as lessons_mod
import untis_desktop.windows.master_data
import untis_desktop.windows.requests as requests_mod
import untis_desktop.windows.settings as settings_mod
import untis_desktop.windows.time_grids as time_grids_mod
import untis_desktop.windows.weighting as weighting_mod
from scheduling_platform.application import MasterKind, UntisService, UntisSession
from untis_desktop.i18n import install_translator
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.registry import RibbonTab, spec
from untis_desktop.theme import BREAK_COLOR, ERROR_COLOR, request_color
from untis_desktop.widgets import master_grid
from untis_desktop.widgets.master_grid import MasterDataGrid

MY_KEYS = (
    "classes",
    "teachers",
    "rooms",
    "subjects",
    "departments",
    "student_groups",
    "time_grids",
    "requests",
    "lessons",
    "weighting",
    "settings",
)

SVC = UntisService()


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _layout_aislado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """La disposición de columnas va a un .ini temporal, no al registro."""
    ini = str(tmp_path / "layout.ini")
    monkeypatch.setattr(
        master_grid, "layout_settings", lambda: QSettings(ini, QSettings.Format.IniFormat)
    )


@pytest.fixture(scope="module")
def anon_session(anon_xml_path: Path) -> UntisSession:
    return SVC.open(anon_xml_path)


def _mini() -> UntisSession:
    s = SVC.new("Colegio Demo")
    for kind, ident in (
        (MasterKind.CLASSES, "5A"),
        (MasterKind.CLASSES, "5B"),
        (MasterKind.TEACHERS, "ANA"),
        (MasterKind.TEACHERS, "BEA"),
        (MasterKind.SUBJECTS, "MAT"),
        (MasterKind.SUBJECTS, "ING"),
        (MasterKind.ROOMS, "R1"),
    ):
        assert SVC.add_master(s, kind, ident).ok
    return s


@pytest.fixture
def bridge(qapp: QApplication) -> Iterator[FacadeBridge]:
    b = FacadeBridge(SVC)
    yield b
    b.set_language("es")


@pytest.fixture
def mini(bridge: FacadeBridge, qapp: QApplication) -> FacadeBridge:
    bridge.attach(_mini())
    qapp.processEvents()
    return bridge


@pytest.fixture
def anon(bridge: FacadeBridge, anon_session: UntisSession, qapp: QApplication) -> FacadeBridge:
    bridge.attach(SVC.snapshot(anon_session))
    qapp.processEvents()
    return bridge


def _make[W: QWidget](qtbot: QtBot, widget: W) -> W:
    qtbot.addWidget(widget)
    return widget


def _flush(qapp: QApplication) -> None:
    qapp.processEvents()
    qapp.processEvents()


def _grid(qtbot: QtBot, bridge: FacadeBridge, kind: MasterKind, key: str = "") -> MasterDataGrid:
    return _make(qtbot, MasterDataGrid(bridge, kind, key or kind.value))


def _col(grid: MasterDataGrid, field: str) -> int:
    return next(i for i, c in enumerate(grid.model.columns) if c.field == field)


def _cell(bridge: FacadeBridge, kind: MasterKind, key: str, field: str) -> str:
    tabla = SVC.master_table(bridge.session, kind)
    col = next(i for i, c in enumerate(tabla.columns) if c.field == field)
    return next(r.cells[col] for r in tabla.rows if r.key == key)


# --------------------------------------------------------------------------- #
# Registro y construcción
# --------------------------------------------------------------------------- #


def test_ventanas_registradas_con_su_pestana() -> None:
    assert spec("lessons").tab is RibbonTab.LESSONS and spec("lessons").order == 1
    assert spec("weighting").tab is RibbonTab.MODULES
    assert spec("settings").tab is RibbonTab.HOME
    for key in ("classes", "teachers", "time_grids", "requests"):
        assert spec(key).tab is RibbonTab.MASTER_DATA
    assert spec("teachers").label("de") == "Lehrer"
    assert spec("requests").label("de") == "Zeitwünsche"
    assert untis_desktop.windows.master_data.MASTER_WINDOWS[0][0] == "classes"


def test_todas_las_ventanas_sin_proyecto_y_con_proyecto(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication, anon_session: UntisSession
) -> None:
    ventanas = {k: _make(qtbot, spec(k).factory(bridge)) for k in MY_KEYS}
    for w in ventanas.values():
        assert hasattr(w, "refresh")
        w.refresh()
    bridge.attach(_mini())
    _flush(qapp)
    teachers = ventanas["teachers"]
    assert isinstance(teachers, MasterDataGrid)
    assert teachers.model.rows[0].key == "ANA"
    bridge.attach(SVC.snapshot(anon_session))
    _flush(qapp)
    assert len(teachers.model.rows) == 116
    tg = ventanas["time_grids"]
    assert isinstance(tg, time_grids_mod.TimeGridsWindow)
    assert tg.tabs.count() == 8


# --------------------------------------------------------------------------- #
# MasterDataGrid
# --------------------------------------------------------------------------- #


def test_edicion_valida_actualiza_proyecto_y_modelo(
    qtbot: QtBot, mini: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, mini, MasterKind.TEACHERS)
    col = _col(grid, "periods_per_day")
    indice = grid.proxy.index(0, col)
    assert grid.proxy.setData(indice, "2-6", Qt.ItemDataRole.EditRole)
    _flush(qapp)
    assert _cell(mini, MasterKind.TEACHERS, "ANA", "periods_per_day") == "2-6"
    assert grid.model.index(0, col).data() == "2-6"
    assert grid.model.error_at("ANA", "periods_per_day") == ""


def test_edicion_invalida_pinta_rojo_y_no_cambia_el_proyecto(
    qtbot: QtBot, mini: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, mini, MasterKind.TEACHERS)
    antes = mini.session.project
    col = _col(grid, "periods_per_day")
    assert not grid.model.setData(grid.model.index(0, col), "6-2", Qt.ItemDataRole.EditRole)
    _flush(qapp)
    assert mini.session.project is antes
    indice = grid.model.index(0, col)
    assert indice.data(Qt.ItemDataRole.BackgroundRole) == QColor(ERROR_COLOR)
    assert "6-2" in str(indice.data(Qt.ItemDataRole.ToolTipRole))
    assert not grid.message.isHidden()
    # Referencia inexistente: también en rojo; corregirla quita el rojo.
    ref = _col(grid, "home_room")
    assert not grid.model.set_cell(0, "home_room", "NO_EXISTE")
    assert grid.model.error_at("ANA", "home_room")
    assert grid.model.set_cell(0, "home_room", "R1")
    assert grid.model.error_at("ANA", "home_room") == ""
    assert grid.model.index(0, ref).data(Qt.ItemDataRole.BackgroundRole) is None


def test_referencias_con_desplegable_y_booleanos_con_casilla(
    qtbot: QtBot, mini: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, mini, MasterKind.TEACHERS)
    ref = _col(grid, "home_room")
    assert grid.model.references(ref) == ("R1",)
    assert grid.model.references(0) is None

    materias = _grid(qtbot, mini, MasterKind.SUBJECTS)
    col = _col(materias, "main_subject")
    indice = materias.model.index(0, col)
    assert indice.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert indice.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    assert materias.model.setData(
        indice, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole
    )
    _flush(qapp)
    assert _cell(mini, MasterKind.SUBJECTS, "MAT", "main_subject") == "x"
    assert (
        materias.model.index(0, col).data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    )


def test_columnas_ocultas_y_reordenadas_se_guardan_y_restauran(
    qtbot: QtBot, mini: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, mini, MasterKind.TEACHERS)
    menu = grid.header_menu()
    acciones = [a for a in menu.actions() if a.isCheckable()]
    assert len(acciones) == len(grid.model.columns) and not acciones[0].isEnabled()
    acciones[2].setChecked(False)  # oculta la columna 2 desde el menú
    grid.move_column(3, 1)
    assert grid.view.horizontalHeader().isSectionHidden(2)

    otra = _grid(qtbot, mini, MasterKind.TEACHERS)
    cabecera = otra.view.horizontalHeader()
    assert cabecera.isSectionHidden(2)
    assert cabecera.visualIndex(3) == 1
    # Una edición recarga el modelo: la disposición sigue ahí.
    assert otra.model.set_cell(0, "name", "Ana")
    _flush(qapp)
    assert cabecera.isSectionHidden(2) and cabecera.visualIndex(3) == 1
    # Otra ventana (otra clave) no hereda la disposición.
    aulas = _grid(qtbot, mini, MasterKind.TEACHERS, "otra_clave")
    assert not aulas.view.horizontalHeader().isSectionHidden(2)
    otra.reset_layout()
    assert not cabecera.isSectionHidden(2) and cabecera.visualIndex(3) == 3


def test_filtro_de_texto_conserva_la_fila_en_blanco(qtbot: QtBot, anon: FacadeBridge) -> None:
    grid = _grid(qtbot, anon, MasterKind.TEACHERS)
    assert grid.proxy.rowCount() == 117
    grid.set_filter("t00")
    visibles = grid.visible_keys()
    assert visibles and all("T00" in k for k in visibles)
    assert grid.proxy.rowCount() == len(visibles) + 1
    grid.set_filter("")
    assert grid.proxy.rowCount() == 117


def test_anadir_y_borrar_entidades(qtbot: QtBot, mini: FacadeBridge, qapp: QApplication) -> None:
    grid = _grid(qtbot, mini, MasterKind.ROOMS)
    blanca = grid.model.index(grid.model.rowCount() - 1, 0)
    assert blanca.flags() & Qt.ItemFlag.ItemIsEditable
    assert grid.model.setData(blanca, "R2", Qt.ItemDataRole.EditRole)
    _flush(qapp)
    assert [r.key for r in grid.model.rows] == ["R1", "R2"]
    # Repetido: rechazado y en rojo en la fila en blanco.
    blanca = grid.model.index(grid.model.rowCount() - 1, 0)
    assert not grid.model.setData(blanca, "R2", Qt.ItemDataRole.EditRole)
    assert blanca.data(Qt.ItemDataRole.BackgroundRole) == QColor(ERROR_COLOR)
    assert grid.select_key("R2")
    assert grid.remove_selected()
    _flush(qapp)
    assert [r.key for r in grid.model.rows] == ["R1"]


def test_borrar_una_entidad_en_uso_muestra_el_motivo(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, anon, MasterKind.TEACHERS)
    usado = next(le.lines[0].teacher for le in SVC.lessons(anon.session) if le.lines[0].teacher)
    antes = anon.session.project
    assert grid.select_key(usado)
    assert not grid.remove_selected()
    assert anon.session.project is antes
    assert not grid.message.isHidden() and "lección" in grid.message.text()


def test_filas_con_hallazgos_llevan_marca(
    qtbot: QtBot, mini: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, mini, MasterKind.ROOMS)
    assert grid.model.setData(
        grid.model.index(grid.model.rowCount() - 1, 0), "R2", Qt.ItemDataRole.EditRole
    )
    _flush(qapp)
    # Cadena de aulas alternativas cíclica: hallazgo del diagnóstico de datos.
    assert grid.model.set_cell(0, "alternative_room", "R2")
    assert grid.model.set_cell(1, "alternative_room", "R1")
    _flush(qapp)
    fila = grid.model.row_of("R1")
    assert grid.model.rows[fila].issues
    indice = grid.model.index(fila, 0)
    assert indice.data(Qt.ItemDataRole.DecorationRole) is not None
    assert grid.model.rows[fila].issues[0] in str(indice.data(Qt.ItemDataRole.ToolTipRole))


# --------------------------------------------------------------------------- #
# Selección sincronizada
# --------------------------------------------------------------------------- #


class _FakeMain(QWidget):
    """Hace de ventana principal: registra qué ventana se pidió abrir."""

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []

    def show_window(self, key: str) -> QWidget:
        self.opened.append(key)
        return self


def test_seleccion_en_datos_maestros_filtra_lecciones_y_deseos(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    clases = _grid(qtbot, anon, MasterKind.CLASSES)
    lecciones = _make(qtbot, lessons_mod.LessonsWindow(anon))
    deseos = _make(qtbot, requests_mod.RequestsWindow(anon))
    clase = clases.model.rows[5].key
    assert clases.select_key(clase)
    assert anon.selection == ("class", clase)
    assert lecciones.mode == "class" and lecciones.entity == clase
    esperadas = {le.number for le in SVC.lessons(anon.session, class_id=clase)}
    assert {le.number for le in lecciones.model.lessons} == esperadas
    assert deseos.kind == "class" and deseos.entity == clase

    # Un profesor elegido en otra ventana: la cuadrícula de profesores lo enfoca.
    profes = _grid(qtbot, anon, MasterKind.TEACHERS)
    anon.select("teacher", "T005")
    assert profes.current_key() == "T005"
    assert lecciones.mode == "teacher" and deseos.kind == "teacher"

    # Botón Deseos: abre la ventana de deseos enfocada en la fila.
    principal = _make(qtbot, _FakeMain())
    aulas = MasterDataGrid(anon, MasterKind.ROOMS)
    aulas.setParent(principal)
    aula = aulas.model.rows[0].key
    assert aulas.select_key(aula)
    aulas.open_requests()
    assert principal.opened == ["requests"]
    assert deseos.kind == "room" and deseos.entity == aula


# --------------------------------------------------------------------------- #
# Deseos de tiempo
# --------------------------------------------------------------------------- #


def test_rejilla_de_deseos_pinta_y_guarda(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, requests_mod.RequestsWindow(anon))
    w.focus_entity("teacher", "T001")
    rejilla = w.grid
    assert rejilla.grid is not None and rejilla.grid.entity_id == "T001"
    recreo = rejilla.grid.breaks[0]
    fila, col = rejilla.position_of(1, recreo)
    assert rejilla.cell_of(fila, col) is None
    item = rejilla.item(fila, col)
    assert item is not None and item.background().color() == QColor(BREAK_COLOR)
    assert item.flags() == Qt.ItemFlag.NoItemFlags

    w.set_paint_value(-3)
    assert w.paint([(1, 2), (1, 3)], -3).ok
    _flush(qapp)
    assert rejilla.value_at(1, 2) == "-3"
    assert rejilla.color_at(1, 3) == request_color(-3)
    assert SVC.request_grid(anon.session, "teacher", "T001").value(1, 2) == -3

    # Día completo desde la cabecera de fila.
    w.set_paint_value(2)
    rejilla.verticalHeader().sectionClicked.emit(1)
    _flush(qapp)
    assert SVC.request_grid(anon.session, "teacher", "T001").day_values[2] == 2
    assert rejilla.value_at(2, None) == "+2"

    # Arrastre con el ratón sobre la fila del miércoles y borrado con clic derecho.
    w.resize(1000, 400)
    w.show()
    qtbot.waitExposed(w)
    w.set_paint_value(1)
    vp = rejilla.viewport()
    QTest.mousePress(
        vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rejilla.cell_center(3, 1)
    )
    QTest.mouseMove(vp, rejilla.cell_center(3, 2))
    QTest.mouseRelease(
        vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rejilla.cell_center(3, 3)
    )
    _flush(qapp)
    vista = SVC.request_grid(anon.session, "teacher", "T001")
    assert [vista.value(3, p) for p in (1, 2, 3)] == [1, 1, 1]
    QTest.mouseClick(
        vp, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, rejilla.cell_center(3, 2)
    )
    _flush(qapp)
    assert SVC.request_grid(anon.session, "teacher", "T001").value(3, 2) == 0
    assert rejilla.value_at(3, 2) == ""


def test_deseos_no_especificados(qtbot: QtBot, anon: FacadeBridge, qapp: QApplication) -> None:
    w = _make(qtbot, requests_mod.RequestsWindow(anon))
    w.focus_entity("teacher", "T002")
    w.unspecified["free_afternoon"].setValue(2)
    _flush(qapp)
    assert ("free_afternoon", 2) in SVC.unspecified_requests(anon.session, "teacher", "T002")
    w.focus_entity("teacher", "T003")
    assert w.unspecified["free_afternoon"].value() == 0
    w.focus_entity("teacher", "T002")
    assert w.unspecified["free_afternoon"].value() == 2


# --------------------------------------------------------------------------- #
# Rejillas de tiempo
# --------------------------------------------------------------------------- #


def test_rejilla_de_tiempo_edita_horas_y_recreos(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, time_grids_mod.TimeGridsWindow(anon))
    page = w.page("Bachillerato")
    assert page.classes.count() == 33
    fila = page.row_of(1)
    item = page.table.item(fila, time_grids_mod.COL_START)
    assert item is not None
    item.setText("06:55")
    _flush(qapp)
    bach = next(g for g in SVC.grids(anon.session) if g.id == "Bachillerato")
    assert bach.periods[0].start == "06:55"
    celda = w.page("Bachillerato").table.item(fila, time_grids_mod.COL_START)
    assert celda is not None and celda.text() == "06:55"

    antes = anon.session.project
    assert not page.edit_period(1, time_grids_mod.COL_END, end="99:99").ok
    assert anon.session.project is antes
    assert page.error_at(1, time_grids_mod.COL_END)
    fin = page.table.item(fila, time_grids_mod.COL_END)
    assert fin is not None and fin.background().color() == QColor(ERROR_COLOR)

    # Recreo: la casilla marca el período y la fila se pinta de gris.
    fila2 = page.row_of(2)
    casilla = page.table.item(fila2, time_grids_mod.COL_BREAK)
    assert casilla is not None
    casilla.setCheckState(Qt.CheckState.Checked)
    _flush(qapp)
    bach = next(g for g in SVC.grids(anon.session) if g.id == "Bachillerato")
    assert bach.periods[1].is_break
    inicio2 = page.table.item(fila2, time_grids_mod.COL_START)
    assert inicio2 is not None and inicio2.background().color() == QColor(BREAK_COLOR)


# --------------------------------------------------------------------------- #
# Lecciones
# --------------------------------------------------------------------------- #


def test_lecciones_anadir_editar_acoplar_desacoplar_borrar(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, lessons_mod.LessonsWindow(anon))
    clase = "K1A"
    w.set_filter("class", clase)
    antes = len(w.model.lessons)

    dialogo = _make(qtbot, lessons_mod.NewLessonDialog(anon))
    dialogo.subject.setCurrentText("MATK1")
    dialogo.teacher.setCurrentText("T001")
    dialogo.check_classes((clase,))
    dialogo.periods.setValue(2)
    materia, profe, clases, periodos = dialogo.values()
    assert (materia, profe, clases, periodos) == ("MATK1", "T001", (clase,), 2)
    resultado = w.create_lesson(materia, profe, clases, periodos)
    assert resultado.ok
    numero = int(resultado.message)
    _flush(qapp)
    assert len(w.model.lessons) == antes + 1
    assert w.current_lesson() == (numero, 0)

    # Edición de la lección (Per/sem) y de la línea (aula); valores inválidos en rojo.
    fila = w.model.row_of(numero)
    assert w.model.edit(fila, "periods_per_week", "3").ok
    _flush(qapp)
    fila = w.model.row_of(numero)
    assert w.model.text(fila, "periods_per_week") == "3"
    assert not w.model.edit(fila, "periods_per_week", "abc").ok
    col = lessons_mod.FIELDS.index("periods_per_week")
    assert w.model.index(fila, col).data(Qt.ItemDataRole.BackgroundRole) == QColor(ERROR_COLOR)
    assert not w.model.edit(fila, "room", "NO_EXISTE").ok
    assert w.model.error_at(numero, 0, "room")
    fijar = w.model.index(fila, lessons_mod.FIELDS.index("fixed"))
    assert w.model.setData(fijar, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    _flush(qapp)
    assert next(le for le in SVC.lessons(anon.session) if le.number == numero).fixed

    # Acoplar: dos filas para la lección; la segunda solo tiene columnas de línea.
    w.select_lesson(numero)
    assert w.couple().ok
    _flush(qapp)
    assert w.model.row_of(numero, 1) == w.model.row_of(numero) + 1
    sub = w.model.row_of(numero, 1)
    assert w.model.text(sub, "periods_per_week") == ""
    assert w.model.text(sub, "subject") == "MATK1"
    assert not w.model.index(sub, col).flags() & Qt.ItemFlag.ItemIsEditable
    assert w.model.edit(sub, "teacher", "T002").ok
    _flush(qapp)
    le = next(le for le in SVC.lessons(anon.session) if le.number == numero)
    assert [x.teacher for x in le.lines] == ["T001", "T002"]

    # Desacoplar la línea 1; con una sola línea, el desacople falla con aviso.
    w.view.setCurrentIndex(w.model.index(w.model.row_of(numero, 1), 0))
    assert w.uncouple().ok
    _flush(qapp)
    assert w.model.row_of(numero, 1) == -1
    w.select_lesson(numero)
    w.view.setCurrentIndex(w.model.index(w.model.row_of(numero), 0))
    assert not w.uncouple().ok
    assert not w.message.isHidden()

    assert w.remove().ok
    _flush(qapp)
    assert w.model.row_of(numero) == -1
    assert len(w.model.lessons) == antes


def test_barra_de_suma_y_sobrecarga(qtbot: QtBot, anon: FacadeBridge, qapp: QApplication) -> None:
    w = _make(qtbot, lessons_mod.LessonsWindow(anon))
    w.set_filter("class", "K1A")
    r = SVC.load_summary(anon.session, "class", "K1A")
    texto = w.sum_bar.text()
    assert f"{r.periods} / " in texto and str(r.capacity) in texto and str(r.placed) in texto
    assert w.sum_bar.property("overloaded") is False
    fila = w.model.row_of(w.model.lessons[0].number)
    assert w.model.edit(fila, "periods_per_week", str(r.capacity + 5)).ok
    _flush(qapp)
    assert w.sum_bar.property("overloaded") is True
    assert ERROR_COLOR in w.sum_bar.styleSheet()
    # Todas: resumen sin capacidad.
    w.set_filter("all")
    assert len(w.model.lessons) == len(SVC.lessons(anon.session))
    assert w.sum_bar.property("overloaded") is False


def test_lecciones_emite_la_leccion_seleccionada(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, lessons_mod.LessonsWindow(anon))
    w.set_filter("teacher", "T028")
    recibidas: list[int] = []
    anon.lesson_selected.connect(recibidas.append)
    numero = w.model.lessons[1].number
    w.view.setCurrentIndex(w.model.index(w.model.row_of(numero), 2))
    assert recibidas[-1] == numero
    w.view.doubleClicked.emit(w.model.index(0, 0))
    assert recibidas[-1] == w.model.lessons[0].number
    # Una lección fuera del filtro: la ventana pasa a Todas y la enfoca.
    fuera = next(
        le.number for le in SVC.lessons(anon.session) if "T028" not in [x.teacher for x in le.lines]
    )
    anon.select_lesson(fuera)
    assert w.mode == "all" and w.current_lesson() == (fuera, 0)


# --------------------------------------------------------------------------- #
# Ponderación
# --------------------------------------------------------------------------- #


def test_ponderacion_deslizador_y_analisis(
    qtbot: QtBot, anon: FacadeBridge, qapp: QApplication
) -> None:
    w = _make(qtbot, weighting_mod.WeightingWindow(anon))
    assert w.tabs.count() == 9
    assert w.tabs.tabText(w.tabs.count() - 1) == "Análisis"
    vistas = SVC.weighting_tabs(anon.session)
    criterio = vistas[0].sliders[0].criterion
    fila = w.sliders[criterio]
    assert fila.label.text() == vistas[0].sliders[0].label
    assert fila.slider.toolTip() == vistas[0].sliders[0].help
    nuevo = 0 if fila.slider.value() else 1
    fila.slider.setValue(nuevo)
    _flush(qapp)
    valores = {s.criterion: s.value for v in SVC.weighting_tabs(anon.session) for s in v.sliders}
    assert valores[criterio] == nuevo
    w.show_help(criterio)
    assert vistas[0].sliders[0].help[:20] in w.help.toPlainText()

    # Dos criterios en 5: aviso de la Fachada visible.
    otros = [s.criterion for v in vistas for s in v.sliders if s.value != 5][:2]
    for c in otros:
        w.set_value(c, 5)
    _flush(qapp)
    assert not w.message.isHidden() and "5" in w.message.text()

    w.show_analysis()
    filas = w.analysis_rows()
    assert filas and [p for _, p in filas] == sorted((p for _, p in filas), reverse=True)
    evaluacion = SVC.evaluation(anon.session)
    assert evaluacion is not None
    assert {c for c, _ in filas} == {c.criterion for c in evaluacion.criteria}


def test_ponderacion_sin_horario(qtbot: QtBot, mini: FacadeBridge) -> None:
    w = _make(qtbot, weighting_mod.WeightingWindow(mini))
    w.show_analysis()
    assert w.analysis_rows() == [] and w.analysis_total.text()


# --------------------------------------------------------------------------- #
# Datos del colegio, idioma, deshacer
# --------------------------------------------------------------------------- #


def test_datos_del_colegio_editables(qtbot: QtBot, mini: FacadeBridge, qapp: QApplication) -> None:
    w = _make(qtbot, settings_mod.SettingsWindow(mini))
    assert w.fields["name"].text() == "Colegio Demo"
    assert w.set_field("name", "Colegio Nuevo").ok
    _flush(qapp)
    assert dict(SVC.school_info(mini.session))["name"] == "Colegio Nuevo"
    antes = mini.session.project
    assert not w.set_field("school_year_begin", "2025-09").ok
    assert mini.session.project is antes and w.error_at("school_year_begin")
    assert ERROR_COLOR in w.fields["school_year_begin"].styleSheet()
    w.language_combo.setCurrentIndex(w.language_combo.findData("de"))
    assert mini.language == "de"
    assert w.labels["name"].text() == SVC.SCHOOL_FIELDS["name"][1]


def test_cambio_de_idioma_retraduce(qtbot: QtBot, anon: FacadeBridge, qapp: QApplication) -> None:
    grid = _grid(qtbot, anon, MasterKind.CLASSES)
    pond = _make(qtbot, weighting_mod.WeightingWindow(anon))
    lecciones = _make(qtbot, lessons_mod.LessonsWindow(anon))
    assert grid.model.headerData(0, Qt.Orientation.Horizontal) == "Nombre corto"
    assert install_translator(qapp, "de")
    try:
        anon.set_language("de")
        assert grid.model.headerData(0, Qt.Orientation.Horizontal) == "Kurzname"
        assert pond.tabs.tabText(0) == SVC.weighting_tabs(anon.session)[0].label_de
        assert lecciones.model.headerData(1, Qt.Orientation.Horizontal) == "Kl"
        assert lecciones.couple_button.text() == "Koppeln"
        assert grid.requests_button.text() == "Zeitwünsche"
        assert pond.tabs.tabText(pond.tabs.count() - 1) == "Analyse"
    finally:
        install_translator(qapp, "es")
        anon.set_language("es")
    assert lecciones.couple_button.text() == "Acoplar"
    assert grid.model.headerData(0, Qt.Orientation.Horizontal) == "Nombre corto"


def test_deshacer_refresca_las_ventanas(
    qtbot: QtBot, mini: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, mini, MasterKind.CLASSES)
    col = _col(grid, "name")
    assert grid.model.set_cell(0, "name", "Quinto A")
    _flush(qapp)
    assert grid.model.index(0, col).data() == "Quinto A"
    assert mini.undo()
    _flush(qapp)
    assert grid.model.index(0, col).data() == ""
    assert mini.redo()
    _flush(qapp)
    assert grid.model.index(0, col).data() == "Quinto A"


def test_desplegable_de_referencias(qtbot: QtBot, mini: FacadeBridge) -> None:
    grid = _grid(qtbot, mini, MasterKind.CLASSES)
    grid.resize(900, 300)
    grid.show()
    qtbot.waitExposed(grid)
    ref = _col(grid, "home_room")
    indice = grid.proxy.index(0, ref)
    grid.view.setCurrentIndex(indice)
    grid.view.edit(indice)
    editor = grid.view.indexWidget(indice) or grid.view.focusWidget()
    assert isinstance(editor, QComboBox)
    assert [editor.itemText(i) for i in range(editor.count())] == ["", "R1"]
