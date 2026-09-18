"""Fachada Untis (`application.untis`): la única puerta de la UI.

Se prueba como la usa la UI: solo a través de `scheduling_platform.application`,
con resultados `EditResult` en vez de excepciones y deshacer/rehacer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scheduling_platform.application import (
    MasterKind,
    OptimizeRequest,
    UntisService,
    UntisSession,
)

SVC = UntisService()


# --------------------------------------------------------------------------- #
# Proyecto mínimo construido solo con la Fachada
# --------------------------------------------------------------------------- #


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


@pytest.fixture(scope="module")
def real_path(anon_xml_path: Path) -> Path:
    return anon_xml_path


# --------------------------------------------------------------------------- #
# Ciclo de vida, deshacer/rehacer
# --------------------------------------------------------------------------- #


def test_nuevo_y_deshacer_rehacer() -> None:
    s = _mini()
    assert s.dirty and s.can_undo
    assert s.undo_label == "Añadir R1"
    antes = len(s.project.rooms)
    assert SVC.undo(s)
    assert len(s.project.rooms) == antes - 1
    assert SVC.redo(s)
    assert len(s.project.rooms) == antes
    assert not SVC.redo(s)


def test_guardar_y_reabrir_rsp(tmp_path: Path) -> None:
    s = _mini()
    destino = SVC.save(s, tmp_path / "demo")  # añade .rsp
    assert destino.suffix == ".rsp" and not s.dirty
    otra = SVC.open(destino)
    assert otra.project == s.project
    assert otra.path == destino


def test_guardar_sin_ruta_falla() -> None:
    with pytest.raises(ValueError):
        SVC.save(_mini())


def test_formato_desconocido(tmp_path: Path) -> None:
    raro = tmp_path / "x.doc"
    raro.write_text("hola")
    with pytest.raises(ValueError):
        SVC.open(raro)


def test_abrir_xml_real_deduce_recreos_y_activa_el_horario(real_path: Path) -> None:
    s = SVC.open(real_path)
    assert s.path is None  # importado: guardar pedirá ruta .rsp
    assert s.active_timetable == s.project.timetables[-1].id
    bach = next(g for g in SVC.grids(s) if g.id == "Bachillerato")
    assert any(p.is_break for p in bach.periods)


# --------------------------------------------------------------------------- #
# Datos maestros
# --------------------------------------------------------------------------- #


def test_tabla_de_datos_maestros_y_edicion() -> None:
    s = _mini()
    tabla = SVC.master_table(s, MasterKind.TEACHERS)
    assert [r.key for r in tabla.rows] == ["ANA", "BEA"]
    campos = [c.field for c in tabla.columns]
    assert campos[0] == "id" and "periods_per_day" in campos
    assert "home_room" in tabla.references and tabla.references["home_room"] == ("R1",)

    assert SVC.set_master_cell(s, MasterKind.TEACHERS, "ANA", "periods_per_day", "2-6").ok
    assert s.project.teacher_by_id["ANA"].periods_per_day.max == 6
    assert SVC.set_master_cell(s, MasterKind.TEACHERS, "ANA", "home_room", "R1").ok


@pytest.mark.parametrize(
    ("campo", "texto"),
    [
        ("periods_per_day", "6-2"),  # min > max
        ("consecutive_max", "abc"),  # no es entero
        ("home_room", "NO_EXISTE"),  # referencia rota
        ("id", "OTRO"),  # no editable
    ],
)
def test_edicion_invalida_devuelve_fallo_sin_cambiar_nada(campo: str, texto: str) -> None:
    s = _mini()
    antes = s.project
    r = SVC.set_master_cell(s, MasterKind.TEACHERS, "ANA", campo, texto)
    assert not r.ok and r.message
    assert s.project == antes


def test_alta_y_baja_de_entidades() -> None:
    s = _mini()
    assert not SVC.add_master(s, MasterKind.CLASSES, "5A").ok  # duplicado
    assert not SVC.add_master(s, MasterKind.CLASSES, "  ").ok
    assert SVC.add_lesson(s, subject="MAT", teacher="ANA", classes=("5A",), periods=2).ok
    usada = SVC.remove_master(s, MasterKind.TEACHERS, "ANA")
    assert not usada.ok and "se usa" in usada.message
    assert SVC.remove_master(s, MasterKind.TEACHERS, "BEA").ok
    assert not SVC.remove_master(s, MasterKind.TEACHERS, "BEA").ok


# --------------------------------------------------------------------------- #
# Lecciones
# --------------------------------------------------------------------------- #


def test_lecciones_alta_edicion_y_acople() -> None:
    s = _mini()
    r = SVC.add_lesson(s, subject="MAT", teacher="ANA", classes=("5A",), periods=4)
    assert r.ok
    numero = int(r.message)
    assert SVC.set_lesson_field(s, numero, "double_periods", "1-2").ok
    assert SVC.set_lesson_field(s, numero, "block", "2,2").ok
    assert SVC.set_lesson_field(s, numero, "fixed", "x").ok
    le = s.project.lesson_by_number[numero]
    assert (le.double_periods.min, le.double_periods.max, le.block, le.fixed) == (
        1,
        2,
        (2, 2),
        True,
    )

    assert SVC.add_line(s, numero).ok
    assert SVC.set_line_field(s, numero, 1, "teacher", "BEA").ok
    fila = SVC.lessons(s, class_id="5A")[0]
    assert fila.is_coupled and [x.teacher for x in fila.lines] == ["ANA", "BEA"]
    assert SVC.lessons(s, teacher_id="BEA")[0].number == numero

    assert not SVC.set_line_field(s, numero, 1, "teacher", "NADIE").ok
    assert not SVC.set_line_field(s, numero, 9, "teacher", "ANA").ok
    assert SVC.remove_line(s, numero, 1).ok
    assert not SVC.remove_line(s, numero, 0).ok  # última línea
    assert SVC.remove_lesson(s, numero).ok
    assert SVC.lessons(s) == ()


def test_lecciones_datos_invalidos() -> None:
    s = _mini()
    assert not SVC.add_lesson(s, subject="NO", teacher="ANA", classes=("5A",), periods=1).ok
    assert not SVC.add_lesson(s, subject="MAT", teacher="ANA", classes=("ZZ",), periods=1).ok
    r = SVC.add_lesson(s, subject="MAT", teacher=None, classes=("5A",), periods=1)
    assert r.ok
    assert not SVC.set_lesson_field(s, int(r.message), "periods_per_week", "-3").ok
    assert not SVC.set_lesson_field(s, int(r.message), "no_existe", "1").ok


def test_resumen_de_carga(real_path: Path) -> None:
    s = SVC.open(real_path)
    carga = SVC.load_summary(s, "class", "K1A")
    assert carga.periods > 0 and carga.capacity > 0
    assert carga.placed <= carga.periods


# --------------------------------------------------------------------------- #
# Deseos y ponderación
# --------------------------------------------------------------------------- #


def test_deseos_de_tiempo() -> None:
    s = _mini()
    assert SVC.set_request(s, "teacher", "ANA", 1, 2, -3).ok
    assert SVC.set_request(s, "teacher", "ANA", 2, None, -1).ok
    rejilla = SVC.request_grid(s, "teacher", "ANA")
    assert rejilla.value(1, 2) == -3 and rejilla.day_values == {2: -1}
    assert SVC.set_request(s, "teacher", "ANA", 1, 2, 0).ok  # 0 borra
    assert SVC.request_grid(s, "teacher", "ANA").value(1, 2) == 0
    assert not SVC.set_request(s, "teacher", "ANA", 1, 2, 7).ok
    assert not SVC.set_request(s, "alien", "ANA", 1, 2, 1).ok


def test_ponderacion_nueve_pestanas() -> None:
    s = _mini()
    tabs = SVC.weighting_tabs(s)
    assert len(tabs) == 9
    assert sum(len(t.sliders) for t in tabs) == 38
    assert next(t for t in tabs if t.tab == "analysis").sliders == ()
    assert all(sl.help for t in tabs for sl in t.sliders)
    assert SVC.set_slider(s, "teacher_gaps", 1).ok
    assert s.project.weighting.teacher_gaps == 1
    assert not SVC.set_slider(s, "teacher_gaps", 9).ok
    assert not SVC.set_slider(s, "inventado", 1).ok
    assert SVC.set_slider(s, "teacher_gaps", 5).message  # ya hay un 5 (class_gaps)


# --------------------------------------------------------------------------- #
# Evaluación, diagnóstico, horarios y planificación (datos reales)
# --------------------------------------------------------------------------- #


def test_evaluacion_y_diagnostico_real(real_path: Path) -> None:
    s = SVC.open(real_path)
    [resumen] = SVC.timetables(s)
    assert resumen.active and resumen.clashes == 7
    ev = SVC.evaluation(s)
    assert ev is not None and ev.clashes == 7 and ev.criteria[0].points >= ev.criteria[-1].points
    diag = SVC.diagnosis(s)
    assert diag.errors > 0  # los 7 choques y los no colocados
    ramas = {i.branch for i in diag.items}
    assert ramas == {"datos", "horario"}
    choques = [i for i in diag.items if i.group == "choque_teacher"]
    assert len(choques) == 7 and all(i.lesson is not None for i in choques)


def test_horario_de_una_clase(real_path: Path) -> None:
    s = SVC.open(real_path)
    grid = SVC.timetable_grid(s, "class", "K1A")
    assert grid.cells and grid.periods
    assert all("K1A" in c.classes for c in grid.cells)
    assert grid.title.startswith("K1A")
    profe = grid.cells[0].teachers[0]
    assert SVC.timetable_grid(s, "teacher", profe).cells


def test_planificacion_mover_desprogramar_fijar(real_path: Path) -> None:
    s = SVC.open(real_path)
    celda = SVC.timetable_grid(s, "class", "K1A").cells[0]
    origen = (celda.day, celda.period)
    objetivos = SVC.move_targets(s, celda.lesson, origen)
    assert objetivos
    libres = [t for t in objetivos if t.feasible and (t.day, t.period) != origen]
    ocupadas = [t for t in objetivos if not t.feasible]
    assert libres and ocupadas and all(t.reason for t in ocupadas)

    destino = (libres[0].day, libres[0].period)
    delta = SVC.move_delta(s, celda.lesson, origen, destino)
    assert delta is not None
    antes = SVC.evaluation(s)
    assert SVC.move_session(s, celda.lesson, origen, destino).ok
    despues = SVC.evaluation(s)
    assert antes is not None and despues is not None
    assert despues.total - antes.total == delta
    assert despues.clashes <= antes.clashes

    bloqueada = ocupadas[0]
    r = SVC.move_session(s, celda.lesson, destino, (bloqueada.day, bloqueada.period))
    assert not r.ok

    assert SVC.unplace_session(s, celda.lesson, destino).ok
    assert any(n == celda.lesson for n, _ in SVC.timetable_grid(s, "class", "K1A").unplaced)
    assert SVC.set_fixed(s, celda.lesson, True).ok
    assert s.project.lesson_by_number[celda.lesson].fixed
    assert SVC.undo(s) and not s.project.lesson_by_number[celda.lesson].fixed


def test_exportar_gpu_con_nombres_cortos(real_path: Path, tmp_path: Path) -> None:
    s = SVC.open(real_path)
    archivos = SVC.export_gpu(s, tmp_path)
    gpu001 = next(f for f in archivos if f.name.upper() == "GPU001.TXT")
    primera = gpu001.read_text(encoding="cp1252").splitlines()[0]
    assert primera.startswith('40,"K1A","T028"')
    xml = SVC.export_xml(s, tmp_path / "vuelta.xml")
    assert SVC.open(xml).project.lessons == s.project.lessons


def test_optimizar_rechaza_estrategia_desconocida() -> None:
    s = _mini()
    out = SVC.optimize(s, OptimizeRequest(strategy="Z"))
    assert not out.ok and out.status == "error"


def test_optimizar_sin_lecciones_no_lanza() -> None:
    out = SVC.optimize(_mini(), OptimizeRequest(strategy="A", time_limit=5))
    assert not out.ok and "lecciones" in out.message


def test_optimizar_estrategia_a_sintetica() -> None:
    import dataclasses

    from scheduling_platform.untis_model import PeriodDef, TimeGrid

    s = _mini()  # la demo aún no tiene rejilla: se crea con el modelo

    rejilla = TimeGrid(
        id="G",
        days=(1, 2, 3),
        periods=tuple(
            PeriodDef(n, 480 + (n - 1) * 50, 480 + (n - 1) * 50 + 45) for n in range(1, 6)
        ),
    )
    s.apply(dataclasses.replace(s.project, time_grids=(rejilla,)), "rejilla")
    for clase in ("5A", "5B"):
        SVC.set_master_cell(s, MasterKind.CLASSES, clase, "time_grid", "G")
    SVC.add_lesson(s, subject="MAT", teacher="ANA", classes=("5A",), periods=4)
    SVC.add_lesson(s, subject="ING", teacher="ANA", classes=("5B",), periods=3)
    SVC.add_lesson(s, subject="ING", teacher="BEA", classes=("5A",), periods=3)
    eventos: list[int] = []
    out = SVC.optimize(
        s, OptimizeRequest(strategy="A", time_limit=5), on_progress=lambda e: eventos.append(e.best)
    )
    assert out.ok, out.message
    assert out.evaluation is not None
    assert out.evaluation.unplaced_periods == 0 and out.evaluation.clashes == 0
    assert s.active_timetable == out.timetable_id
    assert SVC.undo(s)  # optimizar se puede deshacer
    assert s.project.timetable_by_id(out.timetable_id) is None


def test_deseos_no_especificados() -> None:
    s = _mini()
    assert SVC.set_unspecified(s, "teacher", "ANA", "free_afternoon", 2).ok
    assert SVC.unspecified_requests(s, "teacher", "ANA") == (("free_afternoon", 2),)
    assert SVC.set_unspecified(s, "teacher", "ANA", "free_afternoon", 3).ok  # reemplaza
    assert SVC.unspecified_requests(s, "teacher", "ANA") == (("free_afternoon", 3),)
    assert SVC.set_unspecified(s, "teacher", "ANA", "free_afternoon", 0).ok  # borra
    assert SVC.unspecified_requests(s, "teacher", "ANA") == ()
    assert not SVC.set_unspecified(s, "teacher", "ANA", "free_week", 1).ok
    assert not SVC.set_unspecified(s, "teacher", "ANA", "free_day", -1).ok


def test_datos_del_colegio() -> None:
    s = _mini()
    assert dict(SVC.school_info(s))["name"] == "Colegio Demo"
    assert SVC.set_school_field(s, "header1", "Horario 2026-2027").ok
    assert s.project.school.header1 == "Horario 2026-2027"
    assert not SVC.set_school_field(s, "school_year_begin", "2026-01-01").ok
    assert SVC.set_school_field(s, "school_year_begin", "20260801").ok
    assert not SVC.set_school_field(s, "inventado", "x").ok
