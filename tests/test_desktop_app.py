"""App de escritorio (Fase 6, MVP) en modo headless con pytest-qt.

Verifica el flujo vertical: abrir un ``.bjs``, poblar los módulos, editar por el
Data Manager (round-trip a la Fachada), optimizar en el worker y pintar el
horario. Corre con ``QT_QPA_PLATFORM=offscreen`` (ver ``conftest``).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from scheduling_desktop.engine_bridge import EngineBridge, SolveWorker
from scheduling_desktop.main_window import MainWindow
from scheduling_desktop.modules import PAGE_OPTIMIZE
from scheduling_platform.application import (
    BjsProject,
    SolveOutcome,
    save_project,
)
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)


def _problem() -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([3, 3]),
        resources=(
            Resource(ResourceId(0), "Ana", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "10A", frozenset({"group", "group#0"})),
            Resource(
                ResourceId(2),
                "Aula 101",
                frozenset({"room", "room#0", "roomtype#normal"}),
                attributes=(("seats", 30),),
            ),
        ),
        tasks=(
            Task(
                TaskId(0),
                "Mate · c0#0",
                1,
                (
                    ResourceRequirement("teacher#0"),
                    ResourceRequirement("group#0"),
                    ResourceRequirement("room"),
                ),
                attributes=(("size", 25),),
            ),
            Task(
                TaskId(1),
                "Historia · c1#0",
                1,
                (
                    ResourceRequirement("teacher#0"),
                    ResourceRequirement("group#0"),
                    ResourceRequirement("room"),
                ),
                attributes=(("size", 25),),
            ),
        ),
    )


def _make(path: Path) -> None:
    save_project(path, BjsProject.create("Colegio Demo", _problem()))


def test_abrir_puebla_los_modulos(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)

    assert win.windowTitle().startswith("RealSchool — demo.bjs")
    assert win._data._tabs.count() == 4  # docentes/aulas/grupos/materias
    assert win._schedule._focus.count() == 3  # docente/grupo/aula
    assert bridge.dashboard().teachers == 1


def test_edicion_en_data_manager_va_a_la_fachada(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    MainWindow(bridge)
    bridge.open_path(path)

    ok = bridge.rename_resource(0, "Ana Pérez")
    assert ok is True
    assert bridge.session.dirty is True
    tables = bridge.tables()
    assert tables.teachers.rows[0].cells[1] == "Ana Pérez"


def test_optimizar_en_worker_y_pintar_horario(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    win.show_page(PAGE_OPTIMIZE)

    outcomes: list[SolveOutcome] = []
    progress: list[int] = []
    worker = SolveWorker(
        bridge._service,
        bridge.session,
        solver="ortools_cpsat",
        seed=42,
        timeout=10.0,
        structural_only=False,
        cancel=bridge._cancel,
    )
    worker.progressed.connect(lambda pct, _stage: progress.append(pct))
    worker.finished_outcome.connect(lambda outcome: outcomes.append(outcome))
    worker.run()  # síncrono en el hilo de test: determinista

    assert outcomes and outcomes[0].solved is True
    assert progress  # hubo progreso en vivo
    assert bridge.session.project.solution is not None

    focus = next(o for o in bridge.focus_options() if o.kind == "teacher")
    view = bridge.timetable(focus.resource_id)
    assert len(view.cells) == 2
    # El editor dibuja algo tras resolver.
    win._schedule.refresh()
    assert len(win._schedule._scene.items()) > 0


def test_cancelar_marca_el_token(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    bridge.open_path(path)
    bridge.cancel_optimize()
    assert bridge._cancel.is_cancelled() is True


def test_constraint_manager_edita_una_regla(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    cm = win._constraints
    assert cm._list.count() >= 1

    cm._select_rule("teacher_gaps")
    cm._enabled.setChecked(True)
    cm._weight.setValue(7)

    settings = {s.id: s for s in bridge.session.project.constraints.plugins}
    assert settings["teacher_gaps"].enabled is True
    assert settings["teacher_gaps"].weight == 7  # sin robo de selección por reentrancia
    assert bridge.session.dirty is True


def test_validation_center_lista_y_navega(qapp: QApplication, tmp_path: Path) -> None:
    # Docente sobre-asignado en 1 solo período => infactible.
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([1]),
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula", frozenset({"room"})),
        ),
        tasks=(
            Task(
                TaskId(0),
                "A · c#0",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            ),
            Task(
                TaskId(1),
                "B · c#0",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            ),
        ),
    )
    path = tmp_path / "infeasible.bjs"
    save_project(path, BjsProject.create("Infactible", problem))
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    vc = win._validation

    pages: list[str] = []
    vc.navigate.connect(lambda page: pages.append(page))
    vc.refresh()
    assert "INFACTIBLE" in vc._summary.text()
    assert vc._tree.topLevelItemCount() >= 1

    first = vc._tree.topLevelItem(0)
    assert first is not None
    vc._on_item(first, 0)
    assert pages  # navegar dispara la señal a un módulo


def test_mover_clase_y_deshacer(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    MainWindow(bridge)
    bridge.open_path(path)
    worker = SolveWorker(
        bridge._service,
        bridge.session,
        solver="ortools_cpsat",
        seed=42,
        timeout=10.0,
        structural_only=False,
        cancel=bridge._cancel,
    )
    worker.run()

    focus = next(o for o in bridge.focus_options() if o.kind == "teacher")
    cell = bridge.timetable(focus.resource_id).cells[0]
    occupied = {(c.day, c.period) for c in bridge.timetable(focus.resource_id).cells}
    target = next((d, p) for d in range(2) for p in range(3) if (d, p) not in occupied)
    outcome = bridge.move_class(cell.task_id, target[0], target[1])
    assert outcome.solved is True
    assert bridge.can_undo is True
    moved = next(c for c in bridge.timetable(focus.resource_id).cells if c.task_id == cell.task_id)
    assert (moved.day, moved.period) == target

    assert bridge.undo() is True
    back = next(c for c in bridge.timetable(focus.resource_id).cells if c.task_id == cell.task_id)
    assert (back.day, back.period) == (cell.day, cell.period)


def test_drag_feedback_verde_rojo(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    SolveWorker(
        bridge._service,
        bridge.session,
        solver="ortools_cpsat",
        seed=42,
        timeout=10.0,
        structural_only=False,
        cancel=bridge._cancel,
    ).run()

    editor = win._schedule
    editor.refresh()
    focus = next(o for o in bridge.focus_options() if o.kind == "teacher")
    cell = bridge.timetable(focus.resource_id).cells[0]

    editor._on_drag_started(cell.task_id)
    assert editor._overlays  # se pintan los overlays verde/rojo
    assert editor._targets

    red = next((d, p) for (d, p), t in editor._targets.items() if not t.feasible)
    before = bridge.session.project.solution
    editor._on_drag_dropped(*red)
    assert bridge.session.project.solution is before  # soltar en rojo no mueve nada
    assert not editor._overlays  # y limpia el estado del arrastre


def test_plataforma_m5(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)

    # Settings guarda la configuración vía la Fachada.
    win._settings.refresh()
    win._settings._threads.setValue(3)
    win._settings._apply()
    assert bridge.engine_settings().threads == 3

    # Plugin Manager: inventario poblado.
    win._plugins.refresh()
    assert win._plugins._tree.topLevelItemCount() == 3

    # Notificaciones y logs reciben eventos al guardar.
    bridge.save(path)
    assert win._notifications._list.count() >= 1
    assert win._logs._lines


def test_project_manager_crea_version(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)

    pm = win._project
    pm.refresh()
    assert pm._snapshots.count() == 0
    bridge.snapshot()
    pm.refresh()
    assert pm._snapshots.count() == 1
    assert win._import_export._btn_export.isEnabled()


def test_vista_enlazada_clic_a_aula(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    SolveWorker(
        bridge._service,
        bridge.session,
        solver="ortools_cpsat",
        seed=42,
        timeout=10.0,
        structural_only=False,
        cancel=bridge._cancel,
    ).run()

    editor = win._schedule
    editor.refresh()
    focus = next(o for o in bridge.focus_options() if o.kind == "teacher")
    editor._focus.setCurrentIndex(editor._focus.findData(focus.resource_id))
    cell = bridge.timetable(focus.resource_id).cells[0]
    assert cell.room_id >= 0 and cell.group_id >= 0

    editor._inspect(cell.task_id)
    assert editor._btn_room.isEnabled()
    # "Ver horario del aula" cambia el foco a esa aula.
    editor._focus_on(cell.room_id)
    assert editor._focus.currentData() == cell.room_id


def test_bloquear_hora_desde_el_editor(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    SolveWorker(
        bridge._service,
        bridge.session,
        solver="ortools_cpsat",
        seed=42,
        timeout=10.0,
        structural_only=False,
        cancel=bridge._cancel,
    ).run()

    editor = win._schedule
    editor.refresh()
    focus = next(o for o in bridge.focus_options() if o.kind == "teacher")
    assert bridge.can_block(focus.resource_id) is True

    blocked = bridge.toggle_block(focus.resource_id, 0, 2)
    assert blocked is True
    assert (0, 2) in bridge.blocked_hours(focus.resource_id)
    editor.refresh()  # repinta con la celda bloqueada (no lanza)

    # Un aula no se puede bloquear.
    room = next(o for o in bridge.focus_options() if o.kind == "room")
    assert bridge.can_block(room.resource_id) is False


def test_reports_module_se_puebla(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    worker = SolveWorker(
        bridge._service,
        bridge.session,
        solver="ortools_cpsat",
        seed=42,
        timeout=10.0,
        structural_only=False,
        cancel=bridge._cancel,
    )
    worker.run()
    win._reports.refresh()
    assert win._reports._picker.count() == 3
    assert win._reports._table.rowCount() >= 1
