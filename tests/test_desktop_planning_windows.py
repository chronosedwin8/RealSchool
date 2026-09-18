"""Pruebas headless de las ventanas de horarios de `untis_desktop` (R4).

Optimización, Evaluación, Diagnóstico, Diálogo de planificación y Horarios,
sobre el export seudonimizado real (`tests/fixtures/untis_anon.xml`; abrirlo
cuesta ~0,1 s, así que cada prueba que edita abre su propia sesión). El
arrastrar y soltar se prueba con los métodos públicos que llaman los
manejadores de ratón (`begin_drag`, `hover`, `drop_on`...), sin ratón real.
"""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetItem, QWidget
from pytestqt.qtbot import QtBot

from scheduling_platform.application import (
    MasterKind,
    OptimizeOutcome,
    OptimizeProgress,
    OptimizeRequest,
    UntisService,
    UntisSession,
)
from untis_desktop.export import FORMATS, cell_lines, html_to_pdf, timetable_html
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.registry import RibbonTab, load_windows, spec
from untis_desktop.theme import TARGET_NO_COLOR, TARGET_OK_COLOR, fmt_int
from untis_desktop.windows.diagnosis import DiagnosisPanel, entity_of
from untis_desktop.windows.evaluation import EvaluationWindow, fmt_signed
from untis_desktop.windows.optimization import DEFAULT_LIMITS, OptimizationWindow
from untis_desktop.windows.planning import FIXED_ROLE, PlanningWindow
from untis_desktop.windows.timetables import TimetablesWindow

KEYS = ("optimization", "evaluation", "diagnosis", "planning", "timetables")

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def service() -> UntisService:
    return UntisService()


@pytest.fixture(scope="module")
def repaired(service: UntisService, anon_xml_path: Path) -> UntisSession:
    """Sesión con dos horarios: el de Untis y uno reparado (activo)."""
    sesion = service.open(anon_xml_path)
    salida = service.optimize(sesion, OptimizeRequest(strategy="repair", time_limit=10))
    assert salida.ok, salida.message
    return sesion


@pytest.fixture
def bridge(qapp: QApplication, anon_xml_path: Path) -> FacadeBridge:
    """Puente con una sesión propia del export real (se puede editar)."""
    b = FacadeBridge()
    b.attach(b.service.open(anon_xml_path))
    return b


@pytest.fixture
def two_bridge(qapp: QApplication, service: UntisService, repaired: UntisSession) -> FacadeBridge:
    """Puente con una copia independiente de la sesión de dos horarios."""
    b = FacadeBridge(service)
    b.attach(service.snapshot(repaired))
    return b


def _busiest_class(b: FacadeBridge) -> str:
    """La clase con más celdas en el horario activo (buena para arrastrar)."""
    s = b.session
    cuenta = Counter(c for le in s.project.lessons for c in le.classes)
    for clase, _n in cuenta.most_common(10):
        if len(b.service.timetable_grid(s, "class", clase).cells) >= 20:
            return clase
    return cuenta.most_common(1)[0][0]


def _text(item: QTableWidgetItem | None) -> str:
    assert item is not None
    return item.text()


def _number(item: QTableWidgetItem | None) -> int:
    """Entero de una celda con separador de miles (`1.234` -> 1234)."""
    return int(_text(item).replace(".", ""))


def _busy(b: FacadeBridge) -> bool:
    """Lee `busy` sin que mypy lo dé por fijado tras un `assert` anterior."""
    return b.busy


def _planning(qtbot: QtBot, b: FacadeBridge) -> tuple[PlanningWindow, str]:
    w = PlanningWindow(b)
    qtbot.addWidget(w)
    clase = _busiest_class(b)
    assert w.set_focus("class", clase)
    assert w.grid is not None and w.grid.entity_id == clase
    return w, clase


# --------------------------------------------------------------------------- #
# Registro y construcción
# --------------------------------------------------------------------------- #


def test_ventanas_registradas() -> None:
    claves = {s.key for s in load_windows()}
    assert set(KEYS) <= claves
    assert spec("optimization").order == 1
    assert spec("diagnosis").dock == "right"
    assert all(spec(k).tab is RibbonTab.TIMETABLES for k in KEYS)


@pytest.mark.parametrize("key", KEYS)
def test_construye_sin_y_con_sesion(
    qtbot: QtBot, qapp: QApplication, anon_xml_path: Path, key: str
) -> None:
    b = FacadeBridge()
    w = spec(key).factory(b)
    qtbot.addWidget(w)
    refrescar = getattr(w, "refresh", None)
    if callable(refrescar):
        refrescar()
    b.attach(b.service.open(anon_xml_path))
    w.show()
    qtbot.waitUntil(lambda: not getattr(w, "_stale", False), timeout=5000)
    b.set_language("de")
    b.set_language("es")
    assert isinstance(w, QWidget)


# --------------------------------------------------------------------------- #
# Optimización
# --------------------------------------------------------------------------- #


def test_optimizacion_datos_de_control(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = OptimizationWindow(bridge)
    qtbot.addWidget(w)
    assert w.strategy == "A" and w.time_limit.value() == DEFAULT_LIMITS["A"]
    assert not w.placement.isEnabled()
    w.set_strategy("D")
    assert w.time_limit.value() == DEFAULT_LIMITS["D"] and w.placement.isEnabled()
    w.placement.setValue(40)
    w.time_limit.setValue(123)
    w.set_strategy("B")
    assert w.time_limit.value() == DEFAULT_LIMITS["B"]
    w.set_strategy("D")
    assert w.time_limit.value() == 123  # lo editado se recuerda por estrategia
    r = w.request()
    assert (r.strategy, r.time_limit, r.placement_share) == ("D", 123, 0.4)
    w.set_strategy("repair")
    assert w.request().placement_share == 1.0 and w.request().strategy == "repair"
    assert w.start_button.isEnabled()


def test_optimizacion_progreso_y_detener(
    qtbot: QtBot, bridge: FacadeBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = OptimizationWindow(bridge)
    qtbot.addWidget(w)
    bridge.optimize_progress.emit(OptimizeProgress("improvement", 42, 1500, 1200, 3, 2.5))
    bridge.optimize_progress.emit(OptimizeProgress("improvement", 80, 1100, 1100, 1, 4.0))
    assert w.phase_label.text() == "improvement"
    assert w.iteration_label.text() == "80"
    assert w.best_label.text() == "1.100" and w.current_label.text() == "1.100"
    assert w.unplaced_label.text() == "1" and w.elapsed_label.text() == "4.0 s"
    assert w.chart.points == [(2.5, 1200), (4.0, 1100)]
    llamadas: list[bool] = []
    monkeypatch.setattr(bridge, "cancel_optimize", lambda: llamadas.append(True))
    w.stop()
    assert llamadas == [True]


def test_optimizacion_reparar_en_la_ventana(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = OptimizationWindow(bridge)
    ev = EvaluationWindow(bridge)
    qtbot.addWidget(w)
    qtbot.addWidget(ev)
    ev.refresh()
    assert len(list(ev.summaries)) == 1
    ocupado: list[bool] = []
    bridge.busy_changed.connect(ocupado.append)
    w.set_strategy("repair")
    w.time_limit.setValue(10)
    salida = bridge.run_optimize_sync(w.request())
    assert ocupado == [True, False]
    assert salida.ok and salida.evaluation is not None
    assert salida.evaluation.clashes == 0
    assert w.outcome is salida
    assert w.result_label.text() == salida.message
    assert w.log.toPlainText().splitlines() == list(salida.log)
    assert w.chart.points and w.best_label.text() == fmt_int(salida.evaluation.total)
    assert w.start_button.isEnabled() and not w.stop_button.isEnabled()
    ev.refresh()
    assert len(ev.summaries) == 2
    activo = next(t for t in ev.summaries if t.active)
    assert activo.id == salida.timetable_id and activo.clashes == 0
    assert ev.total_label.text() == fmt_int(salida.evaluation.total)


def test_optimizacion_en_hilo_se_detiene(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = OptimizationWindow(bridge)
    qtbot.addWidget(w)
    w.set_strategy("repair")
    w.time_limit.setValue(10)
    with qtbot.waitSignal(bridge.optimize_finished, timeout=30000) as fin:
        assert w.start()
        assert bridge.busy and w.stop_button.isEnabled() and not w.start_button.isEnabled()
        w.stop()
    salida = fin.args[0] if fin.args else None
    assert isinstance(salida, OptimizeOutcome)
    assert salida.status in ("cancelled", "solved", "error")
    assert not _busy(bridge) and w.start_button.isEnabled()


# --------------------------------------------------------------------------- #
# Evaluación
# --------------------------------------------------------------------------- #


def test_evaluacion_cifras_y_desglose(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = EvaluationWindow(bridge)
    qtbot.addWidget(w)
    w.refresh()
    esperado = bridge.service.evaluation(bridge.session)
    assert esperado is not None
    assert w.total_label.text() == fmt_int(esperado.total)
    assert w.unplaced_label.text() == fmt_int(esperado.unplaced_periods)
    assert w.clashes_label.text() == fmt_int(esperado.clashes)
    assert w.soft_label.text() == fmt_int(esperado.soft_points)
    assert w.criteria_table.rowCount() == len(esperado.criteria)
    puntos = [_number(w.criteria_table.item(f, 5)) for f in range(len(esperado.criteria))]
    assert puntos == sorted(puntos, reverse=True)
    assert sum(w.tab_subtotals().values()) == sum(c.points for c in esperado.criteria)
    assert w.tabs_table.rowCount() == len(w.tab_subtotals())


def test_evaluacion_activar_borrar_comparar(qtbot: QtBot, two_bridge: FacadeBridge) -> None:
    b = two_bridge
    w = EvaluationWindow(b)
    qtbot.addWidget(w)
    w.refresh()
    ids = [t.id for t in w.summaries]
    assert len(ids) == 2 and ids[0] == "untis"
    otro = ids[1]
    assert next(t for t in w.summaries if t.active).id == otro

    w.select_ids(ids)
    assert w.selected_ids() == ids and w.compare_button.isEnabled()
    assert w.compare_selected()
    assert not w.compare_box.isHidden()
    ea = b.service.evaluation(b.session, "untis")
    eb = b.service.evaluation(b.session, otro)
    assert ea is not None and eb is not None
    deltas = w.compare("untis", otro)
    assert deltas["total"] == eb.total - ea.total
    pa = {c.criterion: c.points for c in ea.criteria}
    pb = {c.criterion: c.points for c in eb.criteria}
    for k in pa:
        assert deltas[k] == pb.get(k, 0) - pa[k]
    assert _text(w.compare_table.item(0, 3)) == fmt_signed(eb.total - ea.total)

    cambios: list[str] = []
    b.project_changed.connect(cambios.append)
    assert w.activate("untis").ok
    assert b.session.active_timetable == "untis" and cambios
    assert w.total_label.text() == fmt_int(ea.total)

    assert w.delete(otro).ok
    assert [t.id for t in w.summaries] == ["untis"]
    assert w.compared is None and w.compare_box.isHidden()
    assert b.undo()
    w.refresh()
    assert [t.id for t in w.summaries] == ids
    assert not w.activate("no-existe").ok


# --------------------------------------------------------------------------- #
# Diagnóstico
# --------------------------------------------------------------------------- #


def test_diagnostico_arbol_y_salto(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = DiagnosisPanel(bridge)
    qtbot.addWidget(w)
    w.refresh()
    vista = bridge.service.diagnosis(bridge.session)
    por_rama = Counter(i.branch for i in vista.items)
    assert w.branch_counts() == dict(por_rama)
    assert set(w.branch_counts()) == {"datos", "horario"}
    por_grupo = Counter(i.group for i in vista.items if i.branch == "horario")
    assert w.group_counts("horario") == dict(por_grupo)
    # Los errores (choques) van antes que las advertencias.
    grupos = list(w.group_counts("horario"))
    assert grupos[0].startswith("choque_")
    assert str(vista.errors) in w.summary.text()

    con_leccion = next(i for i, it in enumerate(w.items) if it.lesson is not None)
    indice = w.item_index(con_leccion)
    assert indice.isValid()
    with qtbot.waitSignal(bridge.lesson_selected, timeout=1000) as sel:
        w.tree.doubleClicked.emit(indice)
    assert sel.args == [w.items[con_leccion].lesson]

    choque = next(it for it in w.items if it.group == "choque_teacher")
    assert entity_of(choque) == ("teacher", choque.entity_id)
    with qtbot.waitSignal(bridge.selection_changed, timeout=1000) as sel2:
        w.jump(choque)
    assert sel2.args == ["teacher", choque.entity_id]


def test_diagnostico_refresco_perezoso(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = DiagnosisPanel(bridge)
    qtbot.addWidget(w)
    llamadas: list[int] = []
    original = bridge.service.diagnosis

    def contar(*args: object, **kwargs: object) -> object:
        llamadas.append(1)
        return original(bridge.session)

    bridge.service.diagnosis = contar  # type: ignore[method-assign,assignment]
    bridge.notify_changed("x")
    bridge.notify_changed("y")
    qtbot.wait(20)
    assert llamadas == []  # oculto: no calcula
    w.show()
    qtbot.waitUntil(lambda: len(llamadas) == 1, timeout=3000)
    bridge.notify_changed("z")
    bridge.notify_changed("w")
    qtbot.waitUntil(lambda: len(llamadas) == 2, timeout=3000)
    qtbot.wait(400)
    assert len(llamadas) == 2  # dos ediciones seguidas: un solo recálculo


# --------------------------------------------------------------------------- #
# Diálogo de planificación
# --------------------------------------------------------------------------- #


def _drag_first_cell(w: PlanningWindow) -> tuple[int, tuple[int, int]]:
    """Empieza a arrastrar la primera celda no fijada que tenga un destino posible."""
    assert w.grid is not None
    for c in w.grid.cells:
        if c.fixed:
            continue
        w.begin_drag(c.lesson, (c.day, c.period))
        if any(t.feasible and (d, p) != (c.day, c.period) for (d, p), t in w.targets().items()):
            return c.lesson, (c.day, c.period)
    raise AssertionError("ninguna celda tiene destinos posibles")


def test_planificacion_rejilla(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, clase = _planning(qtbot, bridge)
    grid = w.grid
    assert grid is not None
    assert w.table.columnCount() == len(grid.days)
    assert w.table.rowCount() == len(grid.periods)
    cabecera = w.table.verticalHeaderItem(1).text()
    assert grid.periods[1].start in cabecera
    c = grid.cells[0]
    assert c.subject in w.cell_text(c.day, c.period)
    assert bridge.selection == ("class", clase)
    # Sigue la selección sincronizada.
    profesor = c.teachers[0]
    bridge.select("teacher", profesor)
    assert w.focus == ("teacher", profesor)
    assert w.kind_combo.currentData() == "teacher"
    assert w.entity_combo.currentText() == profesor
    bridge.set_language("de")
    assert _text(w.table.horizontalHeaderItem(0)) == "Montag"


def test_planificacion_arrastrar_y_soltar(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, _clase = _planning(qtbot, bridge)
    leccion, origen = _drag_first_cell(w)
    objetivos = w.targets()
    posibles = [k for k, t in objetivos.items() if t.feasible and k != origen]
    imposibles = [k for k, t in objetivos.items() if not t.feasible]
    assert posibles
    visibles_ok = [k for k in posibles if w.item_at(*k) is not None]
    assert visibles_ok
    assert w.cell_color(*visibles_ok[0]) == QColor(TARGET_OK_COLOR)
    visibles_no = [k for k in imposibles if w.item_at(*k) is not None]
    if visibles_no:
        k = visibles_no[0]
        assert w.cell_color(*k) == QColor(TARGET_NO_COLOR)
        item = w.item_at(*k)
        assert item is not None and objetivos[k].reason in item.toolTip()

    destino = visibles_ok[0]
    antes = bridge.service.evaluation(bridge.session)
    assert antes is not None
    llamadas: list[int] = []
    original = bridge.service.move_delta

    def contar(*args: object, **kwargs: object) -> int | None:
        llamadas.append(1)
        return original(bridge.session, leccion, origen, destino)

    bridge.service.move_delta = contar  # type: ignore[method-assign]
    delta = w.hover(*destino)
    assert delta is not None and w.hover(*destino) == delta
    assert llamadas == [1]  # caché por arrastre
    del bridge.service.move_delta  # vuelve al método de la clase
    assert f"{delta:+d}" in w.delta_label.text()

    cambios: list[str] = []
    bridge.project_changed.connect(cambios.append)
    resultado = w.drop_on(*destino)
    assert resultado.ok, resultado.message
    assert cambios and w.drag is None
    despues = bridge.service.evaluation(bridge.session)
    assert despues is not None and despues.total - antes.total == delta
    assert any(c.lesson == leccion for c in w.cells_at(*destino))
    assert w.cell_color(*destino) != QColor(TARGET_OK_COLOR)

    assert bridge.undo()
    w.refresh()
    assert any(c.lesson == leccion for c in w.cells_at(*origen))
    vuelta = bridge.service.evaluation(bridge.session)
    assert vuelta is not None and vuelta.total == antes.total


def test_planificacion_soltar_en_imposible(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, _clase = _planning(qtbot, bridge)
    _leccion, _origen = _drag_first_cell(w)
    imposible = next(k for k, t in w.targets().items() if not t.feasible)
    proyecto = bridge.session.project
    avisos: list[str] = []
    bridge.status.connect(avisos.append)
    assert w.hover(*imposible) is None
    resultado = w.drop_on(*imposible)
    assert not resultado.ok and avisos
    assert bridge.session.project is proyecto
    assert w.drag is None
    assert not w.drop_on(*imposible).ok  # sin arrastre no hace nada


def test_planificacion_f7_y_colocar_desde_la_lista(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, _clase = _planning(qtbot, bridge)
    assert w.grid is not None
    celda = next(c for c in w.grid.cells if not c.fixed)
    antes = dict(w.unplaced_lessons())
    w.select_cell(celda.day, celda.period)
    w.table.setFocus()
    QTest.keyClick(w.table, Qt.Key.Key_F7)
    despues = dict(w.unplaced_lessons())
    assert despues.get(celda.lesson, 0) == antes.get(celda.lesson, 0) + 1
    assert all(c.lesson != celda.lesson for c in w.cells_at(celda.day, celda.period))

    # Arrastrar desde la lista de sin colocar a un destino posible.
    objetivos = w.begin_drag(celda.lesson, None)
    destino = next(
        (t.day, t.period)
        for t in objetivos
        if t.feasible and w.item_at(t.day, t.period) is not None
    )
    assert w.drop_on(*destino).ok
    assert dict(w.unplaced_lessons()).get(celda.lesson, 0) == antes.get(celda.lesson, 0)


def test_planificacion_fijar_y_menu(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, _clase = _planning(qtbot, bridge)
    assert w.grid is not None
    c = next(x for x in w.grid.cells if not x.fixed)
    menu = w.context_menu(c.day, c.period)
    assert menu is not None
    textos = [a.text() for a in menu.actions() if a.text()]
    assert "Fijar" in textos and "Desprogramar (F7)" in textos
    assert any(t.startswith("Intercambiar") for t in textos)
    assert w.context_menu(99, 99) is None

    assert w.toggle_fixed(c.day, c.period).ok
    item = w.item_at(c.day, c.period)
    assert item is not None and item.data(FIXED_ROLE)
    objetivos = w.begin_drag(c.lesson, (c.day, c.period))
    assert all(not t.feasible for t in objetivos if (t.day, t.period) != (c.day, c.period))
    w.end_drag()
    assert not w.unplace(c.day, c.period).ok  # fijada: no se desprograma
    menu = w.context_menu(c.day, c.period)
    assert menu is not None and "Desfijar" in [a.text() for a in menu.actions()]
    assert w.toggle_fixed(c.day, c.period).ok
    item = w.item_at(c.day, c.period)
    assert item is not None and not item.data(FIXED_ROLE)

    with qtbot.waitSignal(bridge.lesson_selected, timeout=1000) as sel:
        w.open_lesson(c.day, c.period)
    assert sel.args == [c.lesson]


def test_planificacion_intercambiar(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, _clase = _planning(qtbot, bridge)
    assert w.grid is not None
    for c in w.grid.cells:
        candidatas = w.begin_swap(c.day, c.period)
        assert _swap_source(w) == (c.lesson, (c.day, c.period))
        for destino in sorted(candidatas):
            otra = w.primary(*destino)
            assert otra is not None
            proyecto = bridge.session.project
            w.begin_swap(c.day, c.period)
            resultado = w.swap_with(*destino)
            assert _swap_source(w) is None
            if resultado.ok:
                assert bridge.session.project is not proyecto
                assert any(x.lesson == c.lesson for x in w.cells_at(*destino))
                assert any(x.lesson == otra.lesson for x in w.cells_at(c.day, c.period))
                return
            assert bridge.session.project is proyecto
        w.cancel_modes()
    pytest.fail("ningún intercambio posible en la clase elegida")


def _swap_source(w: PlanningWindow) -> tuple[int, tuple[int, int]] | None:
    return w.swap_source


# --------------------------------------------------------------------------- #
# Horarios y exportación
# --------------------------------------------------------------------------- #


class _TagCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.open: Counter[str] = Counter()
        self.closed: Counter[str] = Counter()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.open[tag] += 1

    def handle_endtag(self, tag: str) -> None:
        self.closed[tag] += 1


def test_horarios_formatos_y_sincronia(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w = TimetablesWindow(bridge)
    qtbot.addWidget(w)
    w.refresh()
    clase = _busiest_class(bridge)
    pane = w.panes[0]
    assert pane.set_entity("class", clase)
    grid = pane.grid
    assert grid is not None
    c = next(x for x in grid.cells if x.teachers)
    w.select_format("class")
    completo = pane.cell_text(c.day, c.period)
    assert c.subject in completo and c.teachers[0] in completo
    en_celda = grid.at(c.day, c.period)
    w.select_format("compact")
    compacto = pane.cell_text(c.day, c.period)
    assert compacto == "\n".join(cell_lines(en_celda, FORMATS["compact"]))
    assert c.teachers[0] not in compacto
    w.subject_check.setChecked(False)
    w.teacher_check.setChecked(True)
    solo_profes = pane.cell_text(c.day, c.period)
    assert c.teachers[0] in solo_profes and c.subject not in solo_profes.split("\n")

    w.set_pane_count(4)
    assert len(w.visible_panes()) == 4
    assert [p.kind for p in w.visible_panes()] == ["class", "teacher", "room", "subject"]
    profesor = c.teachers[0]
    bridge.select("teacher", profesor)
    assert w.panes[1].entity_id == profesor and w.panes[1].grid is not None
    otra = next(k for k in w.entity_ids("class") if k != clase)
    bridge.select("class", otra)
    assert w.panes[0].entity_id == otra
    w.sync_check.setChecked(False)
    bridge.select("class", clase)
    assert w.panes[0].entity_id == otra
    w.set_pane_count(2)
    assert len(w.visible_panes()) == 2 and w.panes[3].isHidden()


def test_horarios_exportar(qtbot: QtBot, bridge: FacadeBridge, tmp_path: Path) -> None:
    w = TimetablesWindow(bridge)
    qtbot.addWidget(w)
    w.refresh()
    clase = _busiest_class(bridge)
    assert w.panes[0].set_entity("class", clase)
    grid = w.panes[0].grid
    assert grid is not None

    ruta = w.export_html(tmp_path / "clase.html")
    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith("<!DOCTYPE html>")
    assert grid.title in texto
    parser = _TagCounter()
    parser.feed(texto)
    assert parser.open["tr"] == len(grid.periods) + 1
    for tag in ("html", "table", "tr", "td", "th", "div"):
        assert parser.open[tag] == parser.closed[tag], tag
    assert "Lunes" in texto

    pdf = w.export_pdf(tmp_path / "clase.pdf")
    assert pdf.stat().st_size > 1000 and pdf.read_bytes().startswith(b"%PDF")

    ids = [r.key for r in bridge.service.master_table(bridge.session, MasterKind.CLASSES).rows[:3]]
    archivos = w.export_all("class", tmp_path / "todas", ids=ids)
    assert len(archivos) == 3 and all(a.suffix == ".html" for a in archivos)
    unico = w.export_all("class", tmp_path / "todas", pdf=True, ids=ids)
    assert len(unico) == 1 and unico[0].read_bytes().startswith(b"%PDF")

    gpu = w.export_gpu(tmp_path / "gpu")
    assert (tmp_path / "gpu" / "GPU001.TXT").is_file() and gpu
    xml = w.export_xml(tmp_path / "untis.xml")
    assert xml.is_file() and xml.stat().st_size > 1000


def test_export_html_puro(bridge: FacadeBridge, tmp_path: Path) -> None:
    s = bridge.session
    clase = _busiest_class(bridge)
    grid = bridge.service.timetable_grid(s, "class", clase)
    otra = bridge.service.timetable_grid(s, "teacher", grid.cells[0].teachers[0])
    doc = timetable_html([grid, otra], FORMATS["full"], language="de")
    assert doc.count("<table") == 2 and doc.count('class="page"') == 1
    assert "Montag" in doc and grid.title in doc and otra.title in doc
    c = grid.cells[0]
    assert cell_lines([c], FORMATS["compact"]) == [c.subject]
    sin_color = timetable_html([grid], FORMATS["print"])
    assert "background-color: #" not in sin_color.split("</style>")[1]
    assert html_to_pdf(doc, tmp_path / "doble").suffix == ".pdf"


# --------------------------------------------------------------------------- #
# Integración con la ventana principal
# --------------------------------------------------------------------------- #


def test_shell_salto_desde_diagnostico_y_bloqueo(qtbot: QtBot, bridge: FacadeBridge) -> None:
    from untis_desktop.main_window import MainWindow

    m = MainWindow(bridge)
    qtbot.addWidget(m)
    m.show()
    diag = m.window_widget("diagnosis")
    assert isinstance(diag, DiagnosisPanel)
    diag.refresh()
    choque = next(it for it in diag.items if it.group == "choque_teacher" and it.lesson)
    diag.jump(choque)
    assert "planning" in m.open_keys()
    plan = m.window_widget("planning")
    assert isinstance(plan, PlanningWindow)
    assert plan.focus == ("teacher", choque.entity_id)
    assert plan.grid is not None and any(c.lesson == choque.lesson for c in plan.grid.cells)

    m.show_window("optimization")
    m.show_window("evaluation")
    bridge.busy_changed.emit(True)
    subs = {s.widget(): s for s in m.mdi.subWindowList()}
    assert subs[m.window_widget("optimization")].isEnabled()
    assert not subs[m.window_widget("evaluation")].isEnabled()
    bridge.busy_changed.emit(False)
    assert subs[m.window_widget("evaluation")].isEnabled()


def test_planificacion_doble_clic_con_raton(qtbot: QtBot, bridge: FacadeBridge) -> None:
    w, _clase = _planning(qtbot, bridge)
    w.resize(900, 700)
    w.show()
    qtbot.waitExposed(w)
    assert w.grid is not None
    c = w.grid.cells[0]
    item = w.item_at(c.day, c.period)
    assert item is not None
    w.table.scrollToItem(item)
    centro = w.table.visualItemRect(item).center()
    with qtbot.waitSignal(bridge.lesson_selected, timeout=1000) as sel:
        QTest.mouseDClick(
            w.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro
        )
    assert sel.args == [c.lesson]
