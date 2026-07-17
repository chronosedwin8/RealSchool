"""Fachada ``EngineService`` (Fase 5): frontera única GUI↔motor, sin Qt.

Cubre el flujo del MVP: abrir, tablas de entidades, edición básica con round-trip,
validación, optimización estructurada y reconstrucción de la rejilla dia x periodo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scheduling_platform.application import (
    BjsProject,
    CancelToken,
    ConfigError,
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


def test_constraints_catalog_refleja_configuracion(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    catalog = svc.constraints_catalog(session)
    assert catalog  # hay restricciones editables
    # No se ofrece el no-solape estructural (es un invariante del motor).
    ids = {row.rule_id for row in catalog}
    assert "interval_no_overlap" not in ids
    assert "resource_no_overlap" not in ids
    assert "teacher_gaps" in ids
    # Toda blanda permite editar tier y peso; toda dura, no.
    for row in catalog:
        assert row.editable_weight == (row.kind == "soft")

    # Al configurar una regla, el catálogo lo refleja.
    svc.set_rule(session, "teacher_gaps", enabled=True, weight=8, tier=2)
    updated = {r.rule_id: r for r in svc.constraints_catalog(session)}
    assert updated["teacher_gaps"].enabled is True
    assert updated["teacher_gaps"].weight == 8
    assert updated["teacher_gaps"].tier == 2


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


def test_move_class_reubica_y_reoptimiza(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    svc.optimize(session, timeout=10.0)

    # Mover la clase 0 al día 1, período 2 (libre en la rejilla 2x3).
    outcome = svc.move_class(session, 0, 1, 2)
    assert outcome.solved is True
    focus = next(o for o in svc.focus_options(session) if o.kind == "teacher")
    view = svc.timetable(session, focus.resource_id)
    moved = next(c for c in view.cells if c.task_id == 0)
    assert (moved.day, moved.period) == (1, 2)


def test_move_targets_marca_verde_y_rojo(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    svc.optimize(session, timeout=10.0)

    targets = svc.move_targets(session, 0)
    assert len(targets) == 6  # rejilla 2x3
    feasibles = {(t.day, t.period) for t in targets if t.feasible}
    infeasibles = {(t.day, t.period): t.reason for t in targets if not t.feasible}
    # Donde está la otra clase (mismo docente y grupo), la 0 no puede ir: rojo.
    view = svc.timetable(session, next(o.resource_id for o in svc.focus_options(session)))
    other = next(c for c in view.cells if c.task_id == 1)
    assert (other.day, other.period) in infeasibles
    assert feasibles  # y hay celdas verdes disponibles


def test_move_class_a_periodo_invalido_no_cambia(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    svc.optimize(session, timeout=10.0)
    before = session.project.solution
    outcome = svc.move_class(session, 0, 9, 0)  # día fuera de rango
    assert outcome.solved is False
    assert session.project.solution is before  # la sesión no cambió


def test_bloqueo_de_horas_persiste_y_manda(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    # Bloquear al docente (id 0) todo el día 0 (rejilla 2x3).
    svc.set_blocked(session, 0, {(0, 0), (0, 1), (0, 2)})
    assert svc.availability(session, 0) == frozenset({(0, 0), (0, 1), (0, 2)})
    svc.save(session)

    # Persiste al reabrir.
    reopened = svc.open(path)
    assert svc.availability(reopened, 0) == frozenset({(0, 0), (0, 1), (0, 2)})

    # El optimizador respeta el bloqueo: ninguna clase del docente cae el día 0.
    svc.optimize(reopened, timeout=10.0)
    focus = next(o for o in svc.focus_options(reopened) if o.kind == "teacher")
    view = svc.timetable(reopened, focus.resource_id)
    assert all(cell.day != 0 for cell in view.cells)

    # move_targets marca esas celdas como bloqueadas y no se puede mover ahí.
    targets = {(t.day, t.period): t for t in svc.move_targets(reopened, 0)}
    assert targets[(0, 0)].feasible is False
    assert targets[(0, 0)].reason == "hora bloqueada"
    assert svc.move_class(reopened, 0, 0, 0).solved is False


def test_can_block_solo_docentes_y_grupos(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    assert svc.can_block(session, 0) is True  # docente
    assert svc.can_block(session, 1) is True  # grupo
    assert svc.can_block(session, 2) is False  # aula


def test_toggle_block(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    assert svc.toggle_block(session, 0, 1, 1) is True
    assert (1, 1) in svc.availability(session, 0)
    assert svc.toggle_block(session, 0, 1, 1) is False
    assert (1, 1) not in svc.availability(session, 0)


def test_almuerzo_por_defecto_respetado_y_movible(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    # Almuerzo por defecto en el período 1 (índice 1) para todos los docentes.
    n = svc.set_default_lunch(session, 1)
    assert n == 1  # el demo tiene 1 docente
    assert (0, 1) in svc.lunch_hours(session, 0)

    # El optimizador lo respeta: el docente no da clase en el período 1.
    svc.optimize(session, timeout=10.0)
    focus = next(o for o in svc.focus_options(session) if o.kind == "teacher")
    assert all(cell.period != 1 for cell in svc.timetable(session, focus.resource_id).cells)

    # El almuerzo se mueve (día 0: de período 1 a período 2) y persiste.
    svc.toggle_lunch(session, 0, 0, 1)  # quita
    svc.toggle_lunch(session, 0, 0, 2)  # pone
    svc.save(session)
    reopened = svc.open(path)
    day0 = {(d, p) for (d, p) in svc.lunch_hours(reopened, 0) if d == 0}
    assert day0 == {(0, 2)}


def test_reports_del_horario(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    # Sin solución: un aviso.
    assert svc.reports(session)[0].key == "empty"
    svc.optimize(session, timeout=10.0)
    reports = {r.key: r for r in svc.reports(session)}
    assert set(reports) == {"teacher_load", "room_usage", "quality"}
    assert reports["teacher_load"].columns == ("Docente", "Clases", "Períodos")
    assert reports["teacher_load"].rows  # hay docentes con carga


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


_UNTIS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<document version="3.0" xmlns="https://untis.at/untis/XmlInterface">
  <general><header1>Demo</header1></general>
  <timeperiods>
    <timeperiod id="a"><day>1</day><period>1</period><starttime>0800</starttime>
      <endtime>0845</endtime><timegrid>G</timegrid></timeperiod>
    <timeperiod id="b"><day>1</day><period>2</period><starttime>0900</starttime>
      <endtime>0945</endtime><timegrid>G</timegrid></timeperiod>
  </timeperiods>
  <rooms><room id="RM_1"><longname>Aula 1</longname></room></rooms>
  <teachers><teacher id="TR_A"><forename>Ana</forename></teacher></teachers>
  <subjects><subject id="SU_MAT"><longname>Mate</longname></subject></subjects>
  <classes><class id="CL_1"><longname>1A</longname><timegrid>G</timegrid></class></classes>
  <lessons>
    <lesson id="LS_1"><periods>1</periods><lesson_subject id="SU_MAT"/>
      <lesson_teacher id="TR_A"/><lesson_classes id="CL_1"/><timegrid>G</timegrid>
      <times><time><assigned_day>1</assigned_day><assigned_period>1</assigned_period>
        <assigned_room id="RM_1"/></time></times></lesson>
  </lessons>
</document>
"""


def test_export_json(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    svc.optimize(session, timeout=10.0)
    out = svc.export_json(session, tmp_path / "export.json")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert set(doc) == {"manifest", "problem", "solution", "metrics"}
    assert len(doc["problem"]["tasks"]) == 2
    assert doc["solution"] is not None


def test_snapshots(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    assert svc.list_snapshots(session) == ()
    snap = svc.snapshot(session)
    assert snap.exists()
    snaps = svc.list_snapshots(session)
    assert len(snaps) == 1
    # La versión se puede reabrir como proyecto válido.
    restored = svc.open(snap)
    assert restored.project.manifest["project_name"] == "Colegio Demo"


def test_import_untis(tmp_path: Path) -> None:
    xml = tmp_path / "u.xml"
    xml.write_text(_UNTIS_XML, encoding="utf-8")
    svc = EngineService()
    session = svc.import_untis(xml, tmp_path / "imported.bjs")
    assert len(session.project.problem.tasks) == 1
    assert (tmp_path / "imported.bjs").exists()


def test_import_untis_formato_invalido(tmp_path: Path) -> None:
    bad = tmp_path / "x.txt"
    bad.write_text("no soy untis", encoding="utf-8")
    svc = EngineService()
    with pytest.raises(ConfigError):
        svc.import_untis(bad, tmp_path / "out.bjs")


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


def test_engine_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    svc.update_engine_settings(session, threads=4, max_time_seconds=120.0, random_seed=7)
    svc.save(session)
    cfg = svc.engine_settings(svc.open(path))
    assert cfg.threads == 4
    assert cfg.max_time_seconds == 120.0
    assert cfg.random_seed == 7


def test_engine_settings_invalido(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    with pytest.raises(ConfigError):
        svc.update_engine_settings(session, default_solver="inexistente")
