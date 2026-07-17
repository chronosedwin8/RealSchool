"""Fachada ``EngineService`` (Fase 5): frontera única GUI↔motor, sin Qt.

Cubre el flujo del MVP: abrir, tablas de entidades, edición básica con round-trip,
validación, optimización estructurada y reconstrucción de la rejilla dia x periodo.
"""

from __future__ import annotations

from pathlib import Path

from scheduling_platform.application import (
    BjsProject,
    CancelToken,
    EngineService,
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
        grid=TimeGrid.from_segment_lengths([3, 3]),  # 2 dias x 3 periodos
        resources=(
            Resource(ResourceId(0), "Ana Docente", frozenset({"teacher", "teacher#0"})),
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
                "Matemáticas · c0#0",
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


def test_open_y_tablas_de_entidades(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    tables = svc.tables(session)
    assert [r.cells[1] for r in tables.teachers.rows] == ["Ana Docente"]
    assert [r.cells[1] for r in tables.rooms.rows] == ["Aula 101"]
    assert tables.rooms.rows[0].cells[2] == "30"  # cupos
    assert [r.cells[1] for r in tables.groups.rows] == ["10A"]
    # Materias derivadas del nombre de las tareas ("Materia · carga#i").
    assert {r.cells[0] for r in tables.subjects.rows} == {"Matemáticas", "Historia"}


def test_dashboard_cuenta_entidades(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    stats = svc.dashboard(svc.open(path))
    assert (stats.teachers, stats.rooms, stats.groups, stats.subjects) == (1, 1, 1, 2)
    assert stats.tasks == 2
    assert stats.solved is False


def test_edicion_basica_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    svc.rename_resource(session, 0, "Ana Pérez")
    svc.set_room_seats(session, 2, 40)
    dirty_after_edit = session.dirty
    svc.save(session)
    dirty_after_save = session.dirty
    assert dirty_after_edit is True  # editar marca la sesión sucia
    assert dirty_after_save is False  # guardar la limpia
    # Reabrir refleja el cambio.
    reopened = svc.open(path)
    tables = svc.tables(reopened)
    assert tables.teachers.rows[0].cells[1] == "Ana Pérez"
    assert tables.rooms.rows[0].cells[2] == "40"


def test_validate_factible(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    report = svc.validate(svc.open(path))
    assert report.feasible is True
    assert report.errors == ()


def test_set_rule_se_persiste(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    svc.set_rule(session, "teacher_gaps", enabled=True, weight=5)
    svc.save(session)
    reopened = svc.open(path)
    settings = {s.id: s for s in reopened.project.constraints.plugins}
    assert "teacher_gaps" in settings
    assert settings["teacher_gaps"].weight == 5


def test_optimize_devuelve_outcome_y_ubica_las_clases(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    events: list[int] = []
    outcome = svc.optimize(session, timeout=10.0, on_event=lambda e: events.append(e.percentage))
    assert outcome.solved is True
    assert outcome.status == "solved"
    assert session.project.solution is not None
    assert events  # recibió progreso

    # La rejilla ubica cada clase del docente en foco en su (día, período).
    focus = next(o for o in svc.focus_options(session) if o.kind == "teacher")
    view = svc.timetable(session, focus.resource_id)
    assert view.days == 2
    assert view.periods_per_day == 3
    assert len(view.cells) == 2
    for cell in view.cells:
        assert 0 <= cell.day < view.days
        assert 0 <= cell.period < view.periods_per_day
        assert cell.conflict is False
    # Dos clases del mismo docente no pueden compartir celda.
    assert len({(c.day, c.period) for c in view.cells}) == 2


def test_optimize_infactible_no_lanza(tmp_path: Path) -> None:
    # Docente sin disponibilidad para ninguna de sus clases => infactible.
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
    svc = EngineService()
    outcome = svc.optimize(svc.open(path), timeout=5.0)
    assert outcome.solved is False
    assert outcome.status in {"infeasible", "timeout"}


def test_cancel_token_como_should_stop() -> None:
    token = CancelToken()
    assert token.is_cancelled() is False
    token.cancel()
    assert token.is_cancelled() is True
    token.reset()
    assert token.is_cancelled() is False


def test_available_solvers() -> None:
    solvers = EngineService().available_solvers()
    assert "ortools_cpsat" in solvers
