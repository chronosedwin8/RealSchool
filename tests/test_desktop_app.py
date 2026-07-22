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


def test_refresco_agrupado_y_diferido(qapp: QApplication, tmp_path: Path) -> None:
    # Una ráfaga de session_changed (como los ticks de un spinbox) NO debe
    # disparar un refresco por cada uno: se agrupa en uno solo, ya ocioso el hilo.
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    bridge.open_path(path)
    count = 0

    def _count() -> None:
        nonlocal count
        count += 1

    bridge.session_refreshed.connect(_count)
    for _ in range(5):
        bridge.session_changed.emit()  # ráfaga: no refresca aún
    assert count == 0  # diferido: nada mientras la ráfaga ocurre
    qapp.processEvents()
    assert count == 1  # agrupado: un único refresco al quedar ocioso


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
    assert tables.teachers.rows[0].cells[0] == "Ana Pérez"


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
    row_before = cm._list.currentRow()
    cm._enabled.setChecked(True)
    qapp.processEvents()  # dispara cualquier refresco diferido
    cm._weight.setValue(7)
    qapp.processEvents()

    settings = {s.id: s for s in bridge.session.project.constraints.plugins}
    assert settings["teacher_gaps"].enabled is True
    assert settings["teacher_gaps"].weight == 7  # sin robo de selección por reentrancia
    assert bridge.session.dirty is True
    # Activar un check NO debe cambiar la selección ni reconstruir la lista.
    assert cm._current == "teacher_gaps"
    assert cm._list.currentRow() == row_before


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


def test_data_manager_crud_y_carga(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    dm = win._data

    before = bridge.tables().teachers.rows
    tid = bridge.add_teacher("Nuevo Docente")
    dm.refresh()
    assert len(bridge.tables().teachers.rows) == len(before) + 1

    # Carga acoplada: 2 grupos con el docente nuevo (una sola asignación).
    gids = [int(r.key) for r in bridge.tables().groups.rows]
    bridge.add_load(gids, "Coro", [tid], 1)
    assert "Coro" in {r.cells[0] for r in bridge.tables().subjects.rows}
    coro = next(t for t in bridge.session.project.problem.tasks if t.name.startswith("Coro"))
    assert sum(1 for r in coro.requirements if r.tag.startswith("group#")) == len(gids)


def test_celda_materia_ofrece_las_materias_creadas(qapp: QApplication, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QComboBox, QStyleOptionViewItem

    from scheduling_desktop.modules.lessons import _SUBJECT_COL

    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    bridge.add_subject("Filosofía")
    lm = win._lessons
    lm.refresh()
    qapp.processEvents()

    delegate = lm._table.itemDelegateForColumn(_SUBJECT_COL)  # columna Materia
    index = lm._table.model().index(0, _SUBJECT_COL)
    editor = delegate.createEditor(lm._table, QStyleOptionViewItem(), index)
    assert isinstance(editor, QComboBox)
    items = {editor.itemText(i) for i in range(editor.count())}
    assert {"Mate", "Historia", "Filosofía"} <= items  # las materias creadas
    assert editor.isEditable()  # y permite escribir una nueva


def test_leccion_desde_fila_vacia_y_acople_untis(qapp: QApplication, tmp_path: Path) -> None:
    from scheduling_desktop.modules.lessons import _SUBJECT_COL

    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    lm = win._lessons
    lm.refresh()
    qapp.processEvents()

    # Fila vacía estilo Excel: el grupo actual viene precargado; con docentes
    # elegidos, escribir la Materia en la celda CREA la lección.
    assert lm._pending.groups  # grupo actual precargado
    tid = int(bridge.tables().teachers.rows[0].key)
    lm._pending.teachers = [tid]
    blank = len(lm._display)
    blank_item = lm._table.item(blank, _SUBJECT_COL)
    assert blank_item is not None
    blank_item.setText("Robótica")
    qapp.processEvents()
    assert any(d.lesson.subject == "Robótica" for d in lm._display)

    # Acople mostrado como en Untis: ⊞ (nGrupos, nDocentes), colapsado por
    # defecto; clic en la columna N.lec expande a sub-filas y vuelve a colapsar.
    rob = next(d.lesson for d in lm._display if d.lesson.subject == "Robótica")
    mate = next(d.lesson for d in lm._display if d.lesson.subject == "Mate")
    bridge.couple_lessons([list(rob.task_ids), list(mate.task_ids)])
    qapp.processEvents()
    parent = next(d for d in lm._display if d.kind == "parent")
    idx = lm._display.index(parent)
    parent_item = lm._table.item(idx, 0)
    assert parent_item is not None
    text = parent_item.text()
    assert "(" in text and "," in text  # conteo (nGrupos,nDocentes)
    assert all(d.kind != "sub" for d in lm._display)  # colapsado
    lm._on_cell_clicked(idx, 0)
    assert any(d.kind == "sub" for d in lm._display)  # expandido
    lm._on_cell_clicked(idx, 0)
    assert all(d.kind != "sub" for d in lm._display)  # colapsado de nuevo


def test_carga_en_bloques_desde_la_celda(qapp: QApplication, tmp_path: Path) -> None:
    from scheduling_desktop.modules.lessons import _BLOCK_COL

    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    lm = win._lessons
    lm.refresh()
    qapp.processEvents()

    gid = int(bridge.tables().groups.rows[0].key)
    tid = int(bridge.tables().teachers.rows[0].key)
    bridge.add_load([gid], "Alemán", [tid], 4, block=1)
    lm.refresh()
    qapp.processEvents()

    # Editar "Horas dobl." en la celda cambia la lección a bloques de 2.
    idx = next(i for i, d in enumerate(lm._display) if d.lesson.subject == "Alemán")
    item = lm._table.item(idx, _BLOCK_COL)
    assert item is not None
    item.setText("2")
    qapp.processEvents()
    lesson = next(r for r in bridge.lessons(group_id=gid) if r.subject == "Alemán")
    assert lesson.block == 2 and lesson.hours == 4  # 2 dobles, 4 HHs


def test_fila_vacia_crea_registro_estilo_excel(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    dm = win._data
    dm.refresh()

    # Escribir en la fila vacía del final crea el registro (como Untis/Excel).
    model = dm._models["teacher"]
    before = len(bridge.tables().teachers.rows)
    assert model.rowCount() == before + 1  # la fila vacía existe
    assert model.setData(model.index(before, 0), "PROFX") is True
    assert len(bridge.tables().teachers.rows) == before + 1
    assert "PROFX" in {r.cells[0] for r in bridge.tables().teachers.rows}

    # Ediciones encadenadas (rename tras rename) no revientan la interfaz:
    # el refresco va diferido y las vistas persisten.
    tid = next(int(r.key) for r in bridge.tables().teachers.rows if r.cells[0] == "PROFX")
    for i in range(3):
        bridge.rename_resource(tid, f"PROFX{i}")
    qapp.processEvents()
    assert "PROFX2" in {r.cells[0] for r in bridge.tables().teachers.rows}


def test_cerrar_y_reabrir_subventana_no_queda_en_blanco(qapp: QApplication, tmp_path: Path) -> None:
    # Regresión: cerrar una ventana hija ocultaba su widget interno y al
    # reabrirla quedaba una ventana vacía ("la interfaz sin nada").
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    win.show()
    bridge.open_path(path)

    win.show_page("load")
    qapp.processEvents()
    sub = win._subwindows["load"]
    assert win._lessons.isVisible()

    sub.close()
    qapp.processEvents()
    assert win._lessons.isHidden()  # Qt oculta el widget interno al cerrar

    win.show_page("load")
    qapp.processEvents()
    assert win._lessons.isVisible()  # y al reabrir debe volver a verse
    # Y sigue funcionando al ingresar información.
    tables = bridge.tables()
    bridge.add_load(
        [int(tables.groups.rows[0].key)],
        "Química",
        [int(tables.teachers.rows[0].key)],
        1,
    )
    qapp.processEvents()
    assert win._lessons.isVisible()
    assert win._lessons._table.rowCount() >= 1


def test_ventana_de_lecciones_y_mdi(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)

    # MDI: varias ventanas hijas abiertas a la vez (padre/hijo, como Untis).
    win.show_page("data")
    win.show_page("load")
    win.show_page("schedule")
    assert len(win._mdi.subWindowList()) >= 3

    # La ventana de lecciones lista la carga del grupo actual y el total de HHs
    # (+1 fila: la fila vacía (*) de alta estilo Excel).
    lessons = win._lessons
    lessons.refresh()
    assert lessons._mode.currentData() == "group"
    assert lessons._table.rowCount() == 3  # Matemáticas + Historia + fila (*)
    assert lessons._total.text() == "HHs: 2"

    # Cambiar a la vista por docente también puebla la tabla.
    lessons._mode.setCurrentIndex(1)
    assert lessons._table.rowCount() == 3


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


def test_mosaico_de_grupos(qapp: QApplication, tmp_path: Path) -> None:
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
    editor._mosaic_btn.setChecked(True)  # activa el mosaico
    assert not editor._focus.isEnabled()  # el foco se desactiva en mosaico
    assert len(editor._scene.items()) > 0  # dibuja los mini-horarios


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

    # Las aulas también se pueden bloquear (por período), como grupos.
    room = next(o for o in bridge.focus_options() if o.kind == "room")
    assert bridge.can_block(room.resource_id) is True
    assert bridge.block_kind(room.resource_id) == "period"


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


def test_desiderata_module_bloquea_y_copia(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    d = win._desiderata
    d.refresh()
    qapp.processEvents()

    # Grupo: rejilla por período; clic bloquea y clic en cabecera bloquea la columna.
    gi = next(i for i in range(d._resource.count()) if "Grupo" in d._resource.itemText(i))
    d._resource.setCurrentIndex(gi)
    qapp.processEvents()
    gid = d._current()
    assert bridge.block_kind(gid) == "period"
    d._on_cell_clicked(0, 2)
    assert (0, 2) in bridge.blocked_hours(gid)
    d._on_col_clicked(4)  # bloquea el período P5 todos los días
    assert all((day, 4) in bridge.blocked_hours(gid) for day in range(d._table.rowCount()))

    # Docente: rejilla por hora de reloj; fila bloquea el día entero.
    ti = next(i for i in range(d._resource.count()) if "Docente" in d._resource.itemText(i))
    d._resource.setCurrentIndex(ti)
    qapp.processEvents()
    tid = d._current()
    assert bridge.block_kind(tid) == "clock"
    d._on_row_clicked(1)  # martes entero
    assert len([c for c in bridge.teacher_time_blocks(tid) if c[0] == 1]) == d._table.columnCount()


def test_pool_de_clases_fuera_del_horario(qapp: QApplication, tmp_path: Path) -> None:
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
    ed = win._schedule
    ed.refresh()
    qapp.processEvents()
    assert ed._pool.count() == 0  # todo ubicado

    # Sacar una clase del horario -> aparece en el pool.
    assert ed._view_model is not None
    tid = ed._view_model.cells[0].task_id
    bridge.unplace_class(tid)
    qapp.processEvents()
    assert ed._pool.count() == 1

    # Seleccionarla del pool marca las celdas destino; colocarla la saca del pool.
    ed._on_pool_clicked(ed._pool.item(0))
    assert ed._placing_task == tid
    green = next(dp for dp, t in ed._targets.items() if t.feasible)
    ed._on_cell_pressed(*green)
    qapp.processEvents()
    assert tid not in [c.task_id for c in bridge.unplaced_classes()]


def test_semana_lectiva_module_edita_el_marco(qapp: QApplication, tmp_path: Path) -> None:
    from scheduling_desktop.modules.school_week import _BAND_ROW, _START_ROW

    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    sw = win._school_week
    sw.refresh()
    qapp.processEvents()

    # Sin semanas todavía: la rejilla está vacía, los controles deshabilitados y
    # el mensaje guía a crear una (así no parece que "no deja cambiar" nada).
    assert sw._table.columnCount() == 0
    assert sw._days.isEnabled() is False
    assert sw._afternoon.isEnabled() is False
    assert "Nueva" in sw._hint.text()

    # Crear una semana lectiva la puebla con una columna por período y habilita.
    _, periods = bridge.grid_size()
    index = bridge.add_school_week("Bachillerato", max_periods=periods)
    sw.refresh()
    qapp.processEvents()
    assert sw._table.columnCount() == periods
    assert sw._days.isEnabled() is True
    assert sw._afternoon.isEnabled() is True

    # Subir Períodos/día añade columnas (definir P0..P11 aunque la rejilla sea menor).
    sw._periods.setValue(periods + 4)
    qapp.processEvents()
    assert sw._table.columnCount() == periods + 4
    assert bridge.school_weeks()[index].max_periods == periods + 4

    # Autogenerar rellena inicio/fin de todas las horas desde el inicio de P0.
    bridge.set_school_week_period(index, 0, "07:00", "07:45")
    bridge.generate_school_week_times(index, 45, 5)
    sw._reload()
    qapp.processEvents()
    p1 = bridge.school_weeks()[index].periods[1]
    assert (p1.start, p1.end) == ("07:50", "08:35")

    # Aplicar al horario ajusta la rejilla del proyecto al mayor marco (periods+4).
    days, applied = bridge.apply_school_weeks_to_grid()
    assert applied == periods + 4
    assert bridge.grid_size() == (days, periods + 4)

    # Clic en la fila Franja de un período lo marca como Recreo.
    sw._on_cell_clicked(_BAND_ROW, 1)
    qapp.processEvents()
    assert 1 in bridge.school_weeks()[index].breaks
    band = sw._table.item(_BAND_ROW, 1)
    assert band is not None and band.text() == "Recreo"

    # Escribir la hora de reloj en Inicio la persiste en la semana.
    start_item = sw._table.item(_START_ROW, 0)
    assert start_item is not None
    start_item.setText("07:00")
    qapp.processEvents()
    assert bridge.school_weeks()[index].periods[0].start == "07:00"


def test_columna_semana_lectiva_en_la_carga(qapp: QApplication, tmp_path: Path) -> None:
    from scheduling_desktop.modules.lessons import _WEEK_COL

    path = tmp_path / "demo.bjs"
    _make(path)
    bridge = EngineBridge()
    win = MainWindow(bridge)
    bridge.open_path(path)
    bridge.add_school_week("Bachillerato")
    lm = win._lessons
    lm.refresh()
    qapp.processEvents()

    # La columna Semana lect. existe y su combo ofrece las semanas creadas.
    header = lm._table.horizontalHeaderItem(_WEEK_COL)
    assert header is not None and header.text() == "Semana lect."
    assert "Bachillerato" in lm._week_names()

    # Escribir el nombre de la semana en la celda la asigna a la lección.
    lesson = lm._display[0].lesson
    item = lm._table.item(0, _WEEK_COL)
    assert item is not None
    item.setText("Bachillerato")
    qapp.processEvents()
    assert bridge.lesson_school_week(list(lesson.task_ids)) == 0
