"""Marco horario y bloqueos de horas (deseos -3 de columna/día/celda).

Cubre lo nuevo de la Fachada (`time_frame`, `set_time_frame`, `blocked_cells`,
`set_blocked`, `set_requests`, `grid_id_of`, `RequestGrid.period_values`,
`TimetableGrid.blocked`/`is_blocked`), que el generador respeta el marco y el
criterio blando `lesson_period_duration`, además de la interfaz: la ventana de
Deseos (marco por rejilla/por todos, clic en cabecera de columna) y la ventana
de planificación (`toggle_blocked`).

Sigue el estilo de `test_untis_facade.py` (Fachada pura, sesiones `_mini()`
construidas a mano) y de `test_desktop_data_windows.py`/
`test_desktop_planning_windows.py` (`qtbot`, `FacadeBridge`, `_flush`).
"""

from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

import untis_desktop.windows.requests as requests_mod
from scheduling_platform.application import (
    MasterKind,
    OptimizeRequest,
    UntisService,
    UntisSession,
)
from scheduling_platform.untis_model import PeriodDef, TimeGrid
from scheduling_platform.untis_model.diagnostics import diagnose_data
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.widgets.timetable_cells import BLOCKED_ROLE
from untis_desktop.windows.planning import PlanningWindow

SVC = UntisService()


# --------------------------------------------------------------------------- #
# Sesiones de prueba
# --------------------------------------------------------------------------- #


def _mini() -> UntisSession:
    """Colegio mínimo con la rejilla estándar (igual que en `test_untis_facade`)."""
    s = SVC.new("Colegio Demo")
    for kind, ident in (
        (MasterKind.CLASSES, "5A"),
        (MasterKind.CLASSES, "5B"),
        (MasterKind.TEACHERS, "ANA"),
    ):
        assert SVC.add_master(s, kind, ident).ok
    return s


def _grid_session() -> UntisSession:
    """Dos clases sobre una rejilla de 6 horas con un recreo tras la 3.ª (hora 4)."""
    s = SVC.new("Marco")
    for c in ("5A", "5B"):
        assert SVC.add_master(s, MasterKind.CLASSES, c).ok
    assert SVC.add_grid(
        s, "G", days=(1, 2, 3), periods=6, start="08:00", duration=45, gap=0, breaks={3: 15}
    ).ok
    for c in ("5A", "5B"):
        assert SVC.set_master_cell(s, MasterKind.CLASSES, c, "time_grid", "G").ok
    return s


def _sintetico_con_marco() -> UntisSession:
    """Proyecto sintético de `test_optimizar_estrategia_a_sintetica`, sin generar."""
    s = SVC.new("Sintetico")
    for kind, ident in (
        (MasterKind.CLASSES, "5A"),
        (MasterKind.CLASSES, "5B"),
        (MasterKind.TEACHERS, "ANA"),
        (MasterKind.TEACHERS, "BEA"),
        (MasterKind.SUBJECTS, "MAT"),
        (MasterKind.SUBJECTS, "ING"),
    ):
        assert SVC.add_master(s, kind, ident).ok
    rejilla = TimeGrid(
        id="G",
        days=(1, 2, 3),
        periods=tuple(
            PeriodDef(n, 480 + (n - 1) * 50, 480 + (n - 1) * 50 + 45) for n in range(1, 6)
        ),
    )
    s.apply(dataclasses.replace(s.project, time_grids=(rejilla,)), "rejilla")
    for clase in ("5A", "5B"):
        assert SVC.set_master_cell(s, MasterKind.CLASSES, clase, "time_grid", "G").ok
    assert SVC.add_lesson(s, subject="MAT", teacher="ANA", classes=("5A",), periods=4).ok
    assert SVC.add_lesson(s, subject="ING", teacher="ANA", classes=("5B",), periods=3).ok
    assert SVC.add_lesson(s, subject="ING", teacher="BEA", classes=("5A",), periods=3).ok
    return s


def _multi_grid_session() -> UntisSession:
    """Tres clases: 5A y 5B comparten la rejilla estándar; 5C usa otra rejilla."""
    s = SVC.new("Multi")
    for c in ("5A", "5B", "5C"):
        assert SVC.add_master(s, MasterKind.CLASSES, c).ok
    assert SVC.add_grid(s, "Otra", days=(1, 2, 3, 4, 5), periods=4, start="08:00", duration=45).ok
    assert SVC.set_master_cell(s, MasterKind.CLASSES, "5C", "time_grid", "Otra").ok
    return s


def _duration_session() -> tuple[UntisSession, int]:
    """Una clase en una rejilla con una hora de 10 min (tutoría) entre horas de 45."""
    s = SVC.new("Duraciones")
    assert SVC.add_master(s, MasterKind.CLASSES, "6A").ok
    assert SVC.add_master(s, MasterKind.TEACHERS, "PRO").ok
    assert SVC.add_master(s, MasterKind.SUBJECTS, "MAT").ok
    rejilla = TimeGrid(
        id="G2",
        days=(1, 2, 3),
        periods=(
            PeriodDef(1, 480, 480 + 45),
            PeriodDef(2, 525, 525 + 45),
            PeriodDef(3, 570, 570 + 45),
            PeriodDef(4, 615, 615 + 10),
            PeriodDef(5, 630, 630 + 45),
        ),
    )
    s.apply(dataclasses.replace(s.project, time_grids=(rejilla,)), "rejilla")
    assert SVC.set_master_cell(s, MasterKind.CLASSES, "6A", "time_grid", "G2").ok
    r = SVC.add_lesson(s, subject="MAT", teacher="PRO", classes=("6A",), periods=1)
    assert r.ok
    return s, int(r.message)


def _make[W: QWidget](qtbot: QtBot, widget: W) -> W:
    qtbot.addWidget(widget)
    return widget


def _flush(qapp: QApplication) -> None:
    qapp.processEvents()
    qapp.processEvents()


# --------------------------------------------------------------------------- #
# 1. Marco horario
# --------------------------------------------------------------------------- #


def test_marco_horario_por_defecto_es_la_jornada_completa() -> None:
    s = _grid_session()
    marco = SVC.time_frame(s, "class", "5A")
    assert marco.periods == (1, 2, 3, 5, 6, 7)  # 6 lectivas; la 4 es el recreo
    assert (marco.first, marco.last) == (1, 7)
    assert marco.is_full
    assert marco.label == "1-7"


def test_fijar_marco_cierra_fuera_y_deja_libre_dentro_respetando_el_recreo() -> None:
    s = _grid_session()
    assert SVC.set_time_frame(s, "class", ("5A", "5B"), 2, 6).ok

    for clase in ("5A", "5B"):
        marco = SVC.time_frame(s, "class", clase)
        assert (marco.first, marco.last) == (2, 6)
        assert not marco.is_full

        cerradas = SVC.blocked_cells(s, "class", clase)
        esperado = {(d, per) for d in (1, 2, 3) for per in (1, 7)}
        assert cerradas == esperado
        # Las horas de dentro del marco quedan abiertas.
        for d in (1, 2, 3):
            for per in (2, 3, 5, 6):
                assert (d, per) not in cerradas
        # El recreo (hora 4) nunca se toca: no es una hora lectiva.
        assert all(per != 4 for _, per in cerradas)

    rejilla = SVC.request_grid(s, "class", "5A")
    assert rejilla.breaks == (4,)
    assert 4 not in rejilla.period_values


def test_marco_horario_first_mayor_que_last_falla() -> None:
    s = _grid_session()
    antes = s.project
    r = SVC.set_time_frame(s, "class", ("5A",), 6, 2)
    assert not r.ok and r.message
    assert s.project is antes


def test_marco_horario_se_deshace_en_un_solo_paso() -> None:
    s = _grid_session()
    assert SVC.set_time_frame(s, "class", ("5A", "5B"), 2, 6).ok
    assert s.can_undo
    assert "Marco horario" in s.undo_label
    assert SVC.undo(s)
    for clase in ("5A", "5B"):
        assert SVC.blocked_cells(s, "class", clase) == frozenset()
        assert SVC.time_frame(s, "class", clase).is_full


def test_marco_horario_sin_entidades_falla() -> None:
    s = _grid_session()
    assert not SVC.set_time_frame(s, "class", (), 1, 3).ok


def test_marco_horario_entidad_sin_rejilla_falla() -> None:
    vacio = SVC.new(default_grid=False)
    assert not vacio.project.time_grids
    assert SVC.add_master(vacio, MasterKind.CLASSES, "5Z").ok  # sin rejillas: sin asignar
    r = SVC.set_time_frame(vacio, "class", ("5Z",), 1, 2)
    assert not r.ok and "5Z" in r.message


# --------------------------------------------------------------------------- #
# 2. Bloqueos de celdas
# --------------------------------------------------------------------------- #


def test_set_blocked_cierra_y_abre() -> None:
    s = _grid_session()
    assert SVC.blocked_cells(s, "class", "5A") == frozenset()
    assert SVC.set_blocked(s, "class", "5A", [(1, 2), (1, 3)], blocked=True).ok
    assert SVC.blocked_cells(s, "class", "5A") == {(1, 2), (1, 3)}
    assert SVC.set_blocked(s, "class", "5A", [(1, 2)], blocked=False).ok
    assert SVC.blocked_cells(s, "class", "5A") == {(1, 3)}


def test_blocked_cells_y_timetable_grid_is_blocked_coinciden() -> None:
    s = _grid_session()
    assert SVC.set_blocked(s, "class", "5A", [(2, 5)], blocked=True).ok
    cerradas = SVC.blocked_cells(s, "class", "5A")
    grid = SVC.timetable_grid(s, "class", "5A")
    assert grid.blocked == cerradas
    assert grid.is_blocked(2, 5)
    assert not grid.is_blocked(2, 6)
    for d, per in grid.blocked:
        assert grid.is_blocked(d, per)


def test_deseos_de_dia_y_de_hora_completos_cuentan_como_cerradas() -> None:
    s = _grid_session()
    # Día 2 entero imposible.
    assert SVC.set_request(s, "class", "5A", 2, None, -3).ok
    cerradas = SVC.blocked_cells(s, "class", "5A")
    for per in (1, 2, 3, 5, 6, 7):
        assert (2, per) in cerradas
    assert (1, 1) not in cerradas

    # Hora 3 imposible todos los días (la columna entera).
    assert SVC.set_request(s, "class", "5A", None, 3, -3).ok
    cerradas = SVC.blocked_cells(s, "class", "5A")
    for d in (1, 2, 3):
        assert (d, 3) in cerradas


# --------------------------------------------------------------------------- #
# 3. El generador respeta el marco horario
# --------------------------------------------------------------------------- #


def test_optimizar_respeta_el_marco_horario() -> None:
    s = _sintetico_con_marco()
    assert SVC.set_time_frame(s, "class", ("5A", "5B"), 1, 4).ok  # cierra la hora 5
    for clase in ("5A", "5B"):
        assert SVC.blocked_cells(s, "class", clase) == {(d, 5) for d in (1, 2, 3)}

    out = SVC.optimize(s, OptimizeRequest(strategy="A", time_limit=8))
    assert out.ok, out.message
    assert out.evaluation is not None
    assert out.evaluation.unplaced_periods == 0 and out.evaluation.clashes == 0

    for clase in ("5A", "5B"):
        grid = SVC.timetable_grid(s, "class", clase)
        assert grid.cells  # se generó algo
        assert not any(c.period == 5 for c in grid.cells)
        assert not grid.unplaced


# --------------------------------------------------------------------------- #
# 4. `set_requests`: varias entidades, un solo paso, y 0 borra
# --------------------------------------------------------------------------- #


def test_set_requests_varias_entidades_un_solo_deshacer_y_cero_borra() -> None:
    s = _mini()
    assert not SVC.set_requests(s, "class", (), [(1, 1)], -2).ok
    assert not SVC.set_requests(s, "class", ("5A",), [], -2).ok

    assert SVC.set_requests(s, "class", ("5A", "5B"), [(1, 1), (1, 2)], -2).ok
    assert "-2" in s.undo_label and "4" in s.undo_label  # 2 entidades x 2 celdas
    for clase in ("5A", "5B"):
        rejilla = SVC.request_grid(s, "class", clase)
        assert rejilla.value(1, 1) == -2 and rejilla.value(1, 2) == -2

    # Un solo paso deshace las 4 celdas de golpe.
    assert SVC.undo(s)
    for clase in ("5A", "5B"):
        rejilla = SVC.request_grid(s, "class", clase)
        assert rejilla.value(1, 1) == 0 and rejilla.value(1, 2) == 0
    assert SVC.redo(s)

    # Valor 0: borra (deja de existir el deseo, no se guarda como "0").
    antes = len(s.project.time_requests)
    assert SVC.set_requests(s, "class", ("5A", "5B"), [(1, 1), (1, 2)], 0).ok
    assert len(s.project.time_requests) == antes - 4
    for clase in ("5A", "5B"):
        assert SVC.request_grid(s, "class", clase).value(1, 1) == 0


def test_set_requests_dia_y_hora_completos() -> None:
    s = _mini()
    assert SVC.set_requests(s, "teacher", ("ANA",), [(None, 2)], -3).ok  # hora 2, toda la semana
    assert SVC.request_grid(s, "teacher", "ANA").period_values[2] == -3
    assert SVC.set_requests(s, "teacher", ("ANA",), [(1, None)], 1).ok  # lunes entero
    assert SVC.request_grid(s, "teacher", "ANA").day_values[1] == 1


# --------------------------------------------------------------------------- #
# 5. Interfaz: ventana de Deseos y ventana de Planificación
# --------------------------------------------------------------------------- #


def test_grid_id_of_identifica_la_rejilla_de_cada_entidad() -> None:
    s = _multi_grid_session()
    assert SVC.grid_id_of(s, "class", "5A") == "Estándar"
    assert SVC.grid_id_of(s, "class", "5B") == "Estándar"
    assert SVC.grid_id_of(s, "class", "5C") == "Otra"


def test_ventana_deseos_marco_por_rejilla_y_por_todos(qtbot: QtBot, qapp: QApplication) -> None:
    bridge = FacadeBridge(SVC)
    bridge.attach(_multi_grid_session())
    _flush(qapp)
    w = _make(qtbot, requests_mod.RequestsWindow(bridge))
    w.focus_entity("class", "5A")
    assert w.scope == "one"
    assert w.targets() == ["5A"]

    # Alcance "todos los de su rejilla": 5A y 5B (comparten "Estándar"), no 5C.
    w.scope_combo.setCurrentIndex(w.scope_combo.findData("grid"))
    assert sorted(w.targets()) == ["5A", "5B"]
    w.frame_first.setValue(6)
    w.frame_last.setValue(8)
    assert w.apply_time_frame().ok
    _flush(qapp)
    for clase in ("5A", "5B"):
        assert SVC.blocked_cells(bridge.session, "class", clase)
    assert SVC.blocked_cells(bridge.session, "class", "5C") == frozenset()

    # Alcance "todos": ahora también 5C.
    w.scope_combo.setCurrentIndex(w.scope_combo.findData("all"))
    assert sorted(w.targets()) == ["5A", "5B", "5C"]
    w.frame_first.setValue(2)
    w.frame_last.setValue(3)
    assert w.apply_time_frame().ok
    _flush(qapp)
    assert SVC.blocked_cells(bridge.session, "class", "5C")


def test_ventana_deseos_sin_entidad_no_aplica_marco(qtbot: QtBot, qapp: QApplication) -> None:
    bridge = FacadeBridge(SVC)
    bridge.attach(SVC.new(default_grid=False))
    _flush(qapp)
    w = _make(qtbot, requests_mod.RequestsWindow(bridge))
    assert w.targets() == []
    assert not w.apply_time_frame().ok


def test_ventana_deseos_clic_en_cabecera_de_columna_escribe_period_values(
    qtbot: QtBot, qapp: QApplication
) -> None:
    bridge = FacadeBridge(SVC)
    bridge.attach(_mini())
    _flush(qapp)
    w = _make(qtbot, requests_mod.RequestsWindow(bridge))
    w.focus_entity("class", "5A")
    rejilla = w.grid
    assert rejilla.grid is not None
    w.set_paint_value(-3)
    hora = next(p for p in rejilla.grid.periods if p not in rejilla.grid.breaks)
    columna = rejilla.grid.periods.index(hora) + 1
    rejilla.horizontalHeader().sectionClicked.emit(columna)
    _flush(qapp)
    assert SVC.request_grid(bridge.session, "class", "5A").period_values[hora] == -3
    assert rejilla.value_at(None, hora) == "-3"
    # Fila 0 = "toda la semana": el propio valor de la celda no se hereda ahí.
    assert rejilla.grid.own_value(1, hora) == 0
    assert rejilla.grid.value(1, hora) == -3  # pero sí se hereda en las filas de días


def test_planificacion_cerrar_y_abrir_una_hora(qtbot: QtBot, qapp: QApplication) -> None:
    s = _sintetico_con_marco()
    out = SVC.optimize(s, OptimizeRequest(strategy="A", time_limit=8))
    assert out.ok, out.message
    bridge = FacadeBridge(SVC)
    bridge.attach(s)
    _flush(qapp)

    w = _make(qtbot, PlanningWindow(bridge))
    # `PlanningWindow` enfoca de oficio la primera entidad al construirse (sin
    # dibujar nada todavía); si se le pide enfocar esa misma entidad, `set_focus`
    # lo toma por "ya enfocada" y no llama a `refresh()` (`self.grid` se queda en
    # `None`). Se enfoca antes otra clase para forzar un cambio real.
    assert w.set_focus("class", "5B")
    assert w.set_focus("class", "5A")
    assert w.grid is not None
    dia, periodo = w.grid.days[0], w.grid.periods[0].number
    assert not w.grid.is_blocked(dia, periodo)

    assert w.toggle_blocked(dia, periodo).ok
    _flush(qapp)
    assert w.grid is not None and w.grid.is_blocked(dia, periodo)
    item = w.item_at(dia, periodo)
    assert item is not None and item.data(BLOCKED_ROLE) is True
    assert (dia, periodo) in SVC.blocked_cells(bridge.session, "class", "5A")

    assert w.toggle_blocked(dia, periodo).ok
    _flush(qapp)
    assert w.grid is not None and not w.grid.is_blocked(dia, periodo)
    item2 = w.item_at(dia, periodo)
    assert item2 is not None and not item2.data(BLOCKED_ROLE)
    assert (dia, periodo) not in SVC.blocked_cells(bridge.session, "class", "5A")


def test_planificacion_menu_contextual_ofrece_cerrar_o_abrir_hora(
    qtbot: QtBot, qapp: QApplication
) -> None:
    s = _sintetico_con_marco()
    out = SVC.optimize(s, OptimizeRequest(strategy="A", time_limit=8))
    assert out.ok, out.message
    bridge = FacadeBridge(SVC)
    bridge.attach(s)
    _flush(qapp)

    w = _make(qtbot, PlanningWindow(bridge))
    assert w.set_focus("class", "5B")  # ver comentario equivalente más arriba
    assert w.set_focus("class", "5A")
    assert w.grid is not None
    dia, periodo = w.grid.days[0], w.grid.periods[0].number
    menu = w.context_menu(dia, periodo)
    assert menu is not None
    textos = [a.text() for a in menu.actions() if a.text()]
    assert "Cerrar esta hora" in textos

    assert w.toggle_blocked(dia, periodo).ok
    _flush(qapp)
    menu2 = w.context_menu(dia, periodo)
    assert menu2 is not None
    textos2 = [a.text() for a in menu2.actions() if a.text()]
    assert "Abrir esta hora" in textos2


# --------------------------------------------------------------------------- #
# 6. Horas de duración distinta: aviso del Diagnóstico y cierre
# --------------------------------------------------------------------------- #


def test_hora_corta_abierta_se_avisa_y_se_quita_cerrandola() -> None:
    """Una hora mucho más corta que las demás (tutoría de 10 min) abierta para la
    clase se avisa en el Diagnóstico de datos; cerrarla con el marco horario o con
    un bloqueo quita el aviso. Es la respuesta fiel a Untis: un deseo -3 (ADR-040).
    """
    s, _numero = _duration_session()

    def avisos() -> list[str]:
        return [i.code for i in diagnose_data(s.project) if i.code == "hora_corta_abierta"]

    assert avisos() == ["hora_corta_abierta"]
    # La hora 4 (10 min) se cierra para la clase: el aviso desaparece.
    assert SVC.set_requests(s, "class", ["6A"], [(None, 4)], -3).ok
    assert avisos() == []
    SVC.undo(s)
    assert avisos() == ["hora_corta_abierta"]
    # El marco horario 1-3 también la deja fuera.
    assert SVC.set_time_frame(s, "class", ["6A"], 1, 3).ok
    assert avisos() == []
