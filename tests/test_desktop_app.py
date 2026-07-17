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
