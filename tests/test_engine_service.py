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
    # La columna 0 es la Abreviatura (lo que se ve en el horario), como en Untis.
    assert [r.cells[0] for r in tables.teachers.rows] == ["Ana Docente"]
    assert [r.cells[0] for r in tables.rooms.rows] == ["Aula 101"]
    assert tables.rooms.rows[0].cells[2] == "30"  # capacidad
    assert [r.cells[0] for r in tables.groups.rows] == ["10A"]
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
    assert tables.teachers.rows[0].cells[0] == "Ana Pérez"
    assert tables.rooms.rows[0].cells[2] == "40"


def test_crud_entidades(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)

    tid = svc.add_teacher(session, "Bruno")
    gid = svc.add_group(session, "7B", 25)
    rid = svc.add_room(session, "Lab", 20)
    tables = svc.tables(session)
    assert len(tables.teachers.rows) == 2
    assert "Bruno" in {r.cells[0] for r in tables.teachers.rows}
    assert tables.groups.rows[-1].cells[4] == "25"  # tamaño del grupo nuevo
    assert len(tables.rooms.rows) == 2

    # Eliminar el aula nueva; el resto sigue.
    svc.remove_resource(session, rid)
    assert len(svc.tables(session).rooms.rows) == 1

    # Persiste al guardar/reabrir.
    svc.save(session)
    reopened = svc.open(path)
    assert len(svc.tables(reopened).teachers.rows) == 2
    assert {int(g.key) for g in svc.tables(reopened).groups.rows} >= {gid}
    _ = tid


def test_add_load_y_remove_subject(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    tid = next(int(r.key) for r in svc.tables(session).teachers.rows)
    gid = next(int(r.key) for r in svc.tables(session).groups.rows)

    ids = svc.add_load(session, [gid], "Ciencias", [tid], sessions=3)
    assert len(ids) == 3
    assert "Ciencias" in {r.cells[0] for r in svc.tables(session).subjects.rows}
    # La nueva carga se puede optimizar.
    assert svc.optimize(session, timeout=10.0).solved is True

    # Eliminar la materia borra sus clases.
    before = len(session.project.problem.tasks)
    svc.remove_subject(session, "Ciencias")
    assert len(session.project.problem.tasks) == before - 3
    assert "Ciencias" not in {r.cells[0] for r in svc.tables(session).subjects.rows}


def test_add_load_acoplada_varios_docentes_y_grupos(tmp_path: Path) -> None:
    # Una asignación puede acoplar varios docentes y varios grupos (Kopplung).
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    t1 = svc.add_teacher(session, "Bruno")
    g1 = svc.add_group(session, "7B", 20)
    teacher0 = next(int(r.key) for r in svc.tables(session).teachers.rows)
    group0 = next(int(r.key) for r in svc.tables(session).groups.rows)

    ids = svc.add_load(session, [group0, g1], "Banda", [teacher0, t1], sessions=1)
    assert len(ids) == 1
    task = next(t for t in session.project.problem.tasks if int(t.id) == ids[0])
    tags = {req.tag for req in task.requirements}
    # Una sola clase acopla 2 docentes + 2 grupos + un aula del pool.
    assert sum(1 for t in tags if t.startswith("teacher#")) == 2  # co-docencia
    assert sum(1 for t in tags if t.startswith("group#")) == 2  # grupos combinados
    assert "room" in tags
    # Los recursos añadidos (id == número de tag) están en el acople.
    assert f"teacher#{t1}" in tags and f"group#{g1}" in tags


def test_materia_primera_clase(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)

    # Alta de una materia sin clases todavía.
    svc.add_subject(session, "Filosofía")
    assert "Filosofía" in {r.cells[0] for r in svc.tables(session).subjects.rows}
    with pytest.raises(ConfigError):
        svc.add_subject(session, "Filosofía")  # duplicada

    # Renombrar una materia con clases renombra también sus clases.
    svc.rename_subject(session, "Matemáticas", "Cálculo")
    subjects = {r.cells[0] for r in svc.tables(session).subjects.rows}
    assert "Cálculo" in subjects and "Matemáticas" not in subjects
    assert any(t.name.startswith("Cálculo · ") for t in session.project.problem.tasks)

    # Persiste la lista de materias.
    svc.save(session)
    assert "Filosofía" in {r.cells[0] for r in svc.tables(svc.open(path)).subjects.rows}


def test_lecciones_por_grupo_y_docente(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    tid = next(int(r.key) for r in svc.tables(session).teachers.rows)
    gid = next(int(r.key) for r in svc.tables(session).groups.rows)

    # El demo trae 2 lecciones de 1 HH (Matemáticas e Historia) para el grupo.
    rows = svc.lessons(session, group_id=gid)
    assert {(r.subject, r.hours) for r in rows} == {("Matemáticas", 1), ("Historia", 1)}
    # La misma vista por docente (como Untis: por grupo o por profesor).
    assert {r.subject for r in svc.lessons(session, teacher_id=tid)} == {
        "Matemáticas",
        "Historia",
    }

    # Cambiar HHs: subir a 3 y bajar a 2.
    mate = next(r for r in rows if r.subject == "Matemáticas")
    svc.set_lesson_hours(session, list(mate.task_ids), 3)
    mate3 = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Matemáticas")
    assert mate3.hours == 3
    svc.set_lesson_hours(session, list(mate3.task_ids), 2)
    mate2 = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Matemáticas")
    assert mate2.hours == 2

    # Eliminar la lección completa.
    svc.remove_lesson(session, list(mate2.task_ids))
    assert {r.subject for r in svc.lessons(session, group_id=gid)} == {"Historia"}

    # Una lección acoplada aparece con todos sus docentes.
    t2 = svc.add_teacher(session, "COD1")
    ids = svc.add_load(session, [gid], "Deporte", [tid, t2], sessions=2)
    dep = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Deporte")
    assert dep.hours == 2 and len(dep.teachers) == 2
    assert set(dep.task_ids) == set(ids)


def test_acoples_distintas_materias_a_la_misma_hora(tmp_path: Path) -> None:
    # El caso Untis "2502": en una misma hora, varios profesores en varios
    # salones con materias DISTINTAS (BIO11 + GES11 simultáneas).
    resources = (
        Resource(ResourceId(0), "GOMEZC", frozenset({"teacher", "teacher#0"})),
        Resource(ResourceId(1), "PORTILLOD", frozenset({"teacher", "teacher#1"})),
        Resource(
            ResourceId(2), "11GIB2", frozenset({"group", "group#2"}), attributes=(("size", 20),)
        ),
        Resource(
            ResourceId(3), "11GIB1", frozenset({"group", "group#3"}), attributes=(("size", 22),)
        ),
        Resource(ResourceId(4), "C22", frozenset({"room", "room#4"}), attributes=(("seats", 30),)),
        Resource(ResourceId(5), "B38", frozenset({"room", "room#5"}), attributes=(("seats", 30),)),
    )
    seed_task = Task(
        TaskId(0),
        "Relleno · g2#0",
        1,
        (
            ResourceRequirement("teacher#0"),
            ResourceRequirement("group#2"),
            ResourceRequirement("room"),
        ),
    )
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4] * 5), resources=resources, tasks=(seed_task,)
    )
    path = tmp_path / "c.bjs"
    save_project(path, BjsProject.create("C", problem))
    svc = EngineService()
    session = svc.open(path)

    bio = svc.add_load(session, [2], "BIO11", [0], 2, room_ids=[4])
    ges = svc.add_load(session, [3], "GES11", [1], 2, room_ids=[5])
    cid = svc.couple_lessons(session, [bio, ges])

    # La vista del grupo 11GIB2 incluye el partner acoplado (sub-fila de Untis).
    rows = svc.lessons(session, group_id=2)
    assert [(r.subject, r.coupling_id) for r in rows[:2]] == [("BIO11", cid), ("GES11", cid)]

    # El optimizador las pone a la misma hora.
    assert svc.optimize(session, timeout=15.0).solved is True
    solution = session.project.solution
    assert solution is not None
    starts: dict[str, set[int]] = {}
    for assignment in solution.assignments:
        task = session.project.problem.task_by_id(assignment.task_id)
        starts.setdefault(task.name.split(" · ")[0], set()).add(int(assignment.start))
    assert starts["BIO11"] == starts["GES11"]

    # Persiste en el .bjs y se puede desacoplar.
    svc.save(session)
    reopened = svc.open(path)
    row = next(r for r in svc.lessons(reopened) if r.subject == "BIO11")
    assert row.coupling_id == cid
    svc.uncouple_lesson(reopened, list(row.task_ids))
    assert all(
        r.coupling_id == -1 for r in svc.lessons(reopened) if r.subject in ("BIO11", "GES11")
    )

    # HHs distintas no se pueden acoplar.
    extra = svc.add_load(session, [2], "ARTE", [0], 3)
    with pytest.raises(ConfigError):
        svc.couple_lessons(session, [bio, extra])


def test_edicion_inline_de_leccion(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    gid = next(int(r.key) for r in svc.tables(session).groups.rows)
    tid = next(int(r.key) for r in svc.tables(session).teachers.rows)
    t2 = svc.add_teacher(session, "COD2")

    mate = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Matemáticas")
    # Cambiar la materia en la celda.
    svc.set_lesson_subject(session, list(mate.task_ids), "Álgebra")
    alg = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Álgebra")
    # Cambiar los docentes (co-docencia) y verificar.
    svc.set_lesson_teachers(session, list(alg.task_ids), [tid, t2])
    alg2 = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Álgebra")
    assert len(alg2.teachers) == 2
    # Cambiar los grupos.
    g2 = svc.add_group(session, "7C", 18)
    svc.set_lesson_groups(session, list(alg2.task_ids), [gid, g2])
    alg3 = next(r for r in svc.lessons(session, group_id=g2) if r.subject == "Álgebra")
    assert len(alg3.groups) == 2
    # Y sigue optimizando.
    assert svc.optimize(session, timeout=10.0).solved is True


def test_aulas_de_una_leccion(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    gid = next(int(r.key) for r in svc.tables(session).groups.rows)
    room_id = next(int(r.key) for r in svc.tables(session).rooms.rows)

    mate = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Matemáticas")
    assert mate.rooms == ()  # pool: el motor elige

    # Fijar un aula concreta a la lección.
    svc.set_lesson_rooms(session, list(mate.task_ids), [room_id])
    fixed = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Matemáticas")
    assert fixed.room_ids == (room_id,)
    # Y con el aula fijada, sigue siendo optimizable.
    assert svc.optimize(session, timeout=10.0).solved is True

    # Volver al pool (vacío = el motor elige).
    svc.set_lesson_rooms(session, list(fixed.task_ids), [])
    back = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Matemáticas")
    assert back.rooms == ()

    with pytest.raises(ConfigError):
        svc.set_lesson_rooms(session, list(back.task_ids), [999])  # aula inexistente


def test_datos_maestros_estilo_untis(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)

    # Docente: nombre completo, e-mail y sección; grupo: sección y aula propia.
    svc.set_resource_info(session, 0, "full_name", "Acero Rondero Luis Carlos")
    svc.set_resource_info(session, 0, "email", "lacero@colegio.edu.co")
    svc.set_resource_info(session, 0, "section", "P")
    svc.set_resource_info(session, 1, "home_room", "P 25")
    # Materia: color (para pintar el horario) y sección.
    svc.set_subject_info(session, "Matemáticas", "color", "#f4a261")
    svc.set_subject_info(session, "Matemáticas", "section", "P")

    tables = svc.tables(session)
    teacher = tables.teachers.rows[0]
    assert teacher.cells[1] == "Acero Rondero Luis Carlos"
    assert teacher.cells[2] == "lacero@colegio.edu.co"
    assert teacher.cells[3] == "P"
    assert tables.groups.rows[0].cells[3] == "P 25"  # aula propia
    mate = next(r for r in tables.subjects.rows if r.cells[0] == "Matemáticas")
    assert mate.cells[3] == "#f4a261"
    assert svc.subject_colors(session) == {"Matemáticas": "#f4a261"}

    # Persiste al guardar/reabrir, y el rename de materia migra sus datos.
    svc.save(session)
    reopened = svc.open(path)
    assert svc.subject_colors(reopened) == {"Matemáticas": "#f4a261"}
    svc.rename_subject(reopened, "Matemáticas", "Cálculo")
    assert svc.subject_colors(reopened) == {"Cálculo": "#f4a261"}

    # Campo inválido sobre entidad inexistente -> error controlado.
    with pytest.raises(ConfigError):
        svc.set_resource_info(session, 999, "email", "x@y.z")
    with pytest.raises(ConfigError):
        svc.set_subject_info(session, "NoExiste", "color", "#fff")


def test_add_load_rechaza_ids_invalidos(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    with pytest.raises(ConfigError):
        svc.add_load(session, [999], "X", [0], sessions=1)  # grupo inexistente


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
    # Sin distribución para una colocación determinista (este test prueba mover).
    svc.set_options(session, avoid_same_subject_same_day=False)
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


def test_block_kind_por_tipo_de_recurso(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    # Docentes por reloj; grupos y aulas por período (todos se pueden bloquear).
    assert svc.block_kind(session, 0) == "clock"  # docente
    assert svc.block_kind(session, 1) == "period"  # grupo
    assert svc.block_kind(session, 2) == "period"  # aula
    assert all(svc.can_block(session, r) for r in (0, 1, 2))


def test_toggle_block(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    assert svc.toggle_block(session, 0, 1, 1) is True
    assert (1, 1) in svc.availability(session, 0)
    assert svc.toggle_block(session, 0, 1, 1) is False
    assert (1, 1) not in svc.availability(session, 0)


def test_ventana_de_almuerzo_deja_una_hora_libre(tmp_path: Path) -> None:
    # Grupo con 3 clases y una rejilla de 1 día x 4 períodos: la ventana P1-P2
    # (índices 0-1) obliga a dejar >= 1 de esos dos períodos libre para el docente.
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(
            Resource(ResourceId(0), "Ana", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "6A", frozenset({"group", "group#0"})),
            Resource(
                ResourceId(2), "Aula", frozenset({"room", "room#0"}), attributes=(("seats", 30),)
            ),
        ),
        tasks=tuple(
            Task(
                TaskId(i),
                f"Mate · c{i}#0",
                1,
                (
                    ResourceRequirement("teacher#0"),
                    ResourceRequirement("group#0"),
                    ResourceRequirement("room"),
                ),
                attributes=(("size", 25),),
            )
            for i in range(3)
        ),
    )
    path = tmp_path / "lunch.bjs"
    save_project(path, BjsProject.create("Lunch", problem))
    svc = EngineService()
    session = svc.open(path)
    svc.set_lunch_window(session, 0, 1)  # ventana en los períodos 0 y 1
    assert svc.lunch_window(session) is not None

    outcome = svc.optimize(session, timeout=10.0)
    assert outcome.solved is True
    focus = next(o for o in svc.focus_options(session) if o.kind == "teacher")
    periods = {cell.period for cell in svc.timetable(session, focus.resource_id).cells}
    # Al menos uno de los períodos 0 y 1 queda libre (almuerzo).
    assert not {0, 1}.issubset(periods)

    # Persiste como ventana (rango), no como hora fija.
    svc.save(session)
    window = svc.lunch_window(svc.open(path))
    assert window is not None
    assert (window.start, window.end) == (0, 1)


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


def test_semana_lectiva_crud_y_persistencia(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)

    # Alta de dos semanas lectivas (marcos horarios por sección).
    b = svc.add_school_week(session, "Bachillerato", days=5, max_periods=3)
    p = svc.add_school_week(session, "Primaria", days=5)
    assert [w.name for w in svc.school_weeks(session)] == ["Bachillerato", "Primaria"]
    with pytest.raises(ConfigError):
        svc.add_school_week(session, "Bachillerato")  # duplicada

    # Editar campos, recreos y horas de reloj.
    svc.set_school_week_field(session, b, "afternoon_from", 2)
    assert svc.toggle_school_week_break(session, b, 1) is True
    svc.set_school_week_period(session, b, 0, "07:00", "07:10")
    week = svc.school_weeks(session)[b]
    assert week.afternoon_from == 2
    assert week.breaks == (1,)
    assert week.periods[0].start == "07:00"

    # Renombrar y persistir round-trip.
    svc.rename_school_week(session, p, "Primaria baja")
    svc.save(session)
    reopened = svc.open(path)
    names = [w.name for w in svc.school_weeks(reopened)]
    assert names == ["Bachillerato", "Primaria baja"]
    assert svc.school_weeks(reopened)[b].breaks == (1,)


def test_leccion_asignada_a_semana_lectiva_recorta_el_motor(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    per_day = session.project.problem.grid.segments[0].length  # 3 en el demo

    week = svc.add_school_week(session, "Bachillerato")
    svc.toggle_school_week_break(session, week, 1)  # recreo en P1

    gid = next(int(r.key) for r in svc.tables(session).groups.rows)
    mate = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Matemáticas")
    svc.set_lesson_school_week(session, list(mate.task_ids), week)
    assert svc.lesson_school_week(session, list(mate.task_ids)) == week

    # La lección aparece con su semana lectiva asignada.
    same = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Matemáticas")
    assert same.school_week == week

    # El motor recorta el recreo P1 de sus inicios permitidos.
    eff = svc._effective_problem(session.project)
    task = next(t for t in eff.tasks if int(t.id) == mate.task_ids[0])
    periods = {int(s) % per_day for s in (task.allowed_starts or set())}
    assert 1 not in periods
    # Las clases sin semana lectiva no se ven afectadas.
    otra = next(t for t in eff.tasks if int(t.id) not in mate.task_ids)
    assert otra.allowed_starts is None

    # Sigue siendo optimizable respetando el recreo.
    outcome = svc.optimize(session, timeout=10.0)
    assert outcome.solved is True
    assert session.project.solution is not None
    for a in session.project.solution.assignments:
        if int(a.task_id) in mate.task_ids:
            assert int(a.start) % per_day != 1


def test_add_load_con_semana_lectiva_y_baja_reindexa(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    gid = next(int(r.key) for r in svc.tables(session).groups.rows)
    tid = next(int(r.key) for r in svc.tables(session).teachers.rows)

    w0 = svc.add_school_week(session, "Kinder")
    w1 = svc.add_school_week(session, "Bachillerato")
    ids = svc.add_load(session, [gid], "Arte", [tid], sessions=1, school_week=w1)
    assert svc.lesson_school_week(session, ids) == w1

    # Al eliminar la semana anterior (w0), la lección debe reindexar a w0.
    svc.remove_school_week(session, w0)
    assert [w.name for w in svc.school_weeks(session)] == ["Bachillerato"]
    assert svc.lesson_school_week(session, ids) == 0


def test_semana_lectiva_valida_orden_de_horas(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    w = svc.add_school_week(session, "Bachillerato")

    svc.set_school_week_period(session, w, 0, "07:00", "07:45")
    # Fin anterior al inicio en el mismo período.
    with pytest.raises(ConfigError):
        svc.set_school_week_period(session, w, 0, "08:00", "07:00")
    # Formato inválido.
    with pytest.raises(ConfigError):
        svc.set_school_week_period(session, w, 1, "8am", "9am")
    # Inicio anterior al fin del período previo (solape).
    with pytest.raises(ConfigError):
        svc.set_school_week_period(session, w, 1, "07:30", "08:15")
    # Un orden correcto sí se acepta.
    svc.set_school_week_period(session, w, 1, "07:50", "08:35")
    assert svc.school_weeks(session)[w].periods[1].start == "07:50"


def test_semana_lectiva_autogenera_horas(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    w = svc.add_school_week(session, "Primaria", max_periods=4)

    # Sin inicio de P0, no genera.
    with pytest.raises(ConfigError):
        svc.generate_school_week_times(session, w, 45)

    svc.set_school_week_period(session, w, 0, "07:00", "07:45")
    svc.generate_school_week_times(session, w, 45, gap_min=5)
    periods = svc.school_weeks(session)[w].periods
    assert len(periods) == 4  # tope de períodos
    assert (periods[0].start, periods[0].end) == ("07:00", "07:45")
    assert (periods[1].start, periods[1].end) == ("07:50", "08:35")
    assert (periods[3].start, periods[3].end) == ("09:30", "10:15")


def test_opciones_distribucion_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    assert svc.options(session).avoid_same_subject_same_day is True  # por defecto
    svc.set_options(session, avoid_same_subject_same_day=False)
    assert svc.options(session).avoid_same_subject_same_day is False
    svc.save(session)
    assert svc.options(svc.open(path)).avoid_same_subject_same_day is False


def test_distribucion_reparte_la_materia_en_dias_distintos(tmp_path: Path) -> None:
    # 3 horas de una materia en un grupo: con distribución van en 3 días distintos.
    path = tmp_path / "p.bjs"
    problem = SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([2, 2, 2]),  # 3 días x 2 períodos
        resources=(
            Resource(ResourceId(0), "Prof", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "6A", frozenset({"group", "group#0"})),
            Resource(
                ResourceId(2),
                "Aula",
                frozenset({"room", "room#0", "roomtype#normal"}),
                attributes=(("seats", 30),),
            ),
        ),
        tasks=tuple(
            Task(
                TaskId(i),
                f"Mate · c{i}",
                1,
                (
                    ResourceRequirement("teacher#0"),
                    ResourceRequirement("group#0"),
                    ResourceRequirement("room"),
                ),
                attributes=(("size", 25),),
            )
            for i in range(3)
        ),
    )
    save_project(path, BjsProject.create("Demo", problem))
    svc = EngineService()
    session = svc.open(path)

    svc.set_options(session, avoid_same_subject_same_day=True)
    assert svc.optimize(session, timeout=15.0).solved is True
    view = svc.timetable(session, 1)  # grupo
    days = {c.day for c in view.cells if c.subject == "Mate"}
    assert len(days) == 3  # una por día, repartidas


def test_bloqueo_por_reloj_de_docente(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    # Semana con horas: P0 07:00-08:00, P1 08:00-09:00, P2 09:00-10:00.
    w = svc.add_school_week(session, "Primaria", max_periods=3)
    svc.set_school_week_period(session, w, 0, "07:00", "08:00")
    svc.generate_school_week_times(session, w, 60)
    svc.apply_school_weeks_to_grid(session)
    per_day = svc.grid_size(session)[1]

    tid = next(int(r.key) for r in svc.tables(session).teachers.rows)
    assert svc.block_kind(session, tid) == "clock"
    for les in svc.lessons(session, teacher_id=tid):
        svc.set_lesson_school_week(session, list(les.task_ids), w)

    # Bloquear al docente el lunes de 08:00 a 09:00 (hora 8) -> bloquea P1 del lunes.
    assert svc.toggle_time_block(session, tid, 0, 8) is True
    eff = svc._effective_problem(session.project)
    tag = svc._unique_tag_of(session.project.problem, tid, "teacher")
    task = next(t for t in eff.tasks if any(r.tag == tag for r in t.requirements))
    monday = {int(s) % per_day for s in (task.allowed_starts or set()) if int(s) < per_day}
    assert 1 not in monday  # P1 del lunes (08:00-09:00) bloqueado
    assert 0 in monday and 2 in monday  # P0 y P2 siguen libres


def test_copiar_desiderata_a_recursos_del_mismo_tipo(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    g1 = next(int(r.key) for r in svc.tables(session).groups.rows)
    g2 = svc.add_group(session, "10B", 25)
    g3 = svc.add_group(session, "10C", 25)
    t1 = next(int(r.key) for r in svc.tables(session).teachers.rows)

    # Bloqueos por período en el grupo fuente.
    svc.set_blocked(session, g1, {(0, 2), (0, 3), (1, 2)})
    n = svc.copy_blocks(session, g1, [g2, g3, t1])  # t1 es docente: se ignora
    assert n == 2  # solo los dos grupos
    assert svc.availability(session, g2) == svc.availability(session, g1)
    assert svc.availability(session, g3) == svc.availability(session, g1)
    assert svc.availability(session, t1) == frozenset()  # el docente no recibió nada


def test_aplicar_semana_lectiva_ajusta_la_rejilla(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    assert svc.grid_size(session) == (2, 3)  # rejilla del demo

    svc.add_school_week(session, "Bachillerato", days=5, max_periods=10)
    svc.optimize(session, timeout=10.0)
    had_solution = session.project.solution is not None
    assert had_solution

    days, periods = svc.apply_school_weeks_to_grid(session)
    assert (days, periods) == (5, 10)
    assert svc.grid_size(session) == (5, 10)
    assert session.project.solution is None  # cambio estructural: se reoptimiza
    # Y el horario más grande sigue siendo optimizable.
    assert svc.optimize(session, timeout=10.0).solved is True


def test_horario_muestra_horas_de_la_semana_lectiva(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    w = svc.add_school_week(session, "Primaria", max_periods=3)
    svc.set_school_week_period(session, w, 0, "07:00", "07:45")
    svc.generate_school_week_times(session, w, 45, gap_min=5)

    gid = next(int(r.key) for r in svc.tables(session).groups.rows)
    for les in svc.lessons(session, group_id=gid):
        svc.set_lesson_school_week(session, list(les.task_ids), w)
    assert svc.optimize(session, timeout=10.0).solved is True

    # La columna de períodos del grupo lleva las horas de reloj de su semana.
    group_view = svc.timetable(session, gid)
    assert group_view.period_clocks[0] == ("07:00", "07:45")
    assert group_view.period_clocks[1] == ("07:50", "08:35")
    # Cada casilla del docente lleva la hora de inicio/fin de su clase.
    tid = next(int(r.key) for r in svc.tables(session).teachers.rows)
    teacher_view = svc.timetable(session, tid)
    with_clock = [c for c in teacher_view.cells if c.start_clock]
    assert with_clock and all(c.end_clock for c in with_clock)


def test_semana_lectiva_tope_de_periodos_recorta_el_motor(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    _make(path)
    svc = EngineService()
    session = svc.open(path)
    per_day = session.project.problem.grid.segments[0].length  # 3 en el demo

    w = svc.add_school_week(session, "Corta", max_periods=2)  # solo P0, P1
    gid = next(int(r.key) for r in svc.tables(session).groups.rows)
    mate = next(r for r in svc.lessons(session, group_id=gid) if r.subject == "Matemáticas")
    svc.set_lesson_school_week(session, list(mate.task_ids), w)

    eff = svc._effective_problem(session.project)
    task = next(t for t in eff.tasks if int(t.id) == mate.task_ids[0])
    periods = {int(s) % per_day for s in (task.allowed_starts or set())}
    assert periods <= {0, 1}  # el período 2 queda fuera del tope
