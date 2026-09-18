"""Pruebas completas con el export real del curso 2026-2027 (XML + archivos GPU).

Los datos son del colegio y **no se versionan** (`tests/fixtures/real/`, ignorado
por git): sin ellos, todo este archivo se salta. Con ellos se comprueba, de
extremo a extremo y contra lo que el propio Untis escribió:

- que XML y GPU describen el mismo colegio, lección a lección y celda a celda;
- que nuestro `GPU001.TXT` (el de MiUntisWeb) es idéntico al de Untis;
- que se cargan los deseos reales de GPU016 que el XML no trae;
- que se genera un horario **desde cero** que respeta todos los deseos -3, sin
  choques, y que se compara con el que publicó Untis con la misma vara;
- que un colegio (una sección entera) se puede volver a teclear desde cero solo
  con la Fachada y generar su horario.
"""

from __future__ import annotations

import dataclasses
import re
import time
from collections import Counter
from pathlib import Path

import pytest

from scheduling_platform.application import (
    MasterKind,
    OptimizeRequest,
    UntisService,
    UntisSession,
)
from scheduling_platform.bridge import UntisTranslator, timetable_to_solution
from scheduling_platform.bridge.repair import repair
from scheduling_platform.engine import ValidationEngine
from scheduling_platform.interop.gpu import read_gpu, write_gpu
from scheduling_platform.interop.rsp import load_rsp, save_rsp
from scheduling_platform.interop.xml import read_xml, write_xml
from scheduling_platform.untis_model import EntityKind, UntisProject, diagnose_data
from scheduling_platform.untis_model.evaluation import Evaluator

EXPORT = Path(__file__).parent / "fixtures" / "real" / "export_2026_2027"
XML = EXPORT / "untis.xml"

pytestmark = pytest.mark.skipif(
    not XML.is_file(), reason="Falta el export real 2026-2027 (datos privados del colegio)"
)

SVC = UntisService()


@pytest.fixture(scope="module")
def sesion() -> UntisSession:
    """El XML abierto como lo abre el usuario: con recreos, hora 0 y deseos de GPU016."""
    return SVC.open(XML)


@pytest.fixture(scope="module")
def proyecto(sesion: UntisSession) -> UntisProject:
    return sesion.project


@pytest.fixture(scope="module")
def gpu() -> UntisProject:
    return read_gpu(EXPORT)


def _gpu_lines(path: Path) -> Counter[str]:
    texto = path.read_bytes().decode("cp1252", "untis-cp1252")
    return Counter(ln.strip() for ln in texto.splitlines() if ln.strip())


# --------------------------------------------------------------------------- #
# Datos: XML y GPU describen el mismo colegio
# --------------------------------------------------------------------------- #


def test_xml_datos_basicos(proyecto: UntisProject) -> None:
    assert (len(proyecto.classes), len(proyecto.teachers), len(proyecto.rooms)) == (82, 154, 96)
    assert len(proyecto.lessons) == 884
    assert len(proyecto.time_grids) == 6
    assert max(len(le.lines) for le in proyecto.lessons) == 44
    assert [i for i in diagnose_data(proyecto) if i.is_error] == []


def test_numeros_de_leccion_iguales_a_gpu002(proyecto: UntisProject) -> None:
    """Las líneas del id llevan dos cifras: `LS_134500` es la lección 1345."""
    gpu002 = {
        int(ln.split(",")[0])
        for ln in (EXPORT / "GPU002.TXT").read_text(encoding="cp1252").splitlines()
        if ln.strip()
    }
    assert {le.number for le in proyecto.lessons} == gpu002


def test_gpu_y_xml_describen_el_mismo_colegio(proyecto: UntisProject, gpu: UntisProject) -> None:
    for coleccion in ("classes", "rooms", "subjects", "departments", "lessons"):
        assert len(getattr(gpu, coleccion)) == len(getattr(proyecto, coleccion)), coleccion
    assert {t.id for t in proyecto.teachers} <= {t.id for t in gpu.teachers}
    x, g = proyecto.lesson_by_number, gpu.lesson_by_number
    assert set(x) == set(g)
    for n, le in x.items():
        assert len(le.lines) == len(g[n].lines), n
        assert le.periods_per_week == g[n].periods_per_week, n
        assert sorted(filter(None, le.teachers)) == sorted(filter(None, g[n].teachers)), n
    celdas_xml = {(a.lesson_number, a.day, a.period) for a in proyecto.timetables[0].assignments}
    celdas_gpu = {(a.lesson_number, a.day, a.period) for a in gpu.timetables[0].assignments}
    assert celdas_xml == celdas_gpu


def test_hora_cero_detectada(proyecto: UntisProject, gpu: UntisProject) -> None:
    """El colegio numera sus períodos desde 0 en Untis (GPU001), el XML desde 1."""
    assert proyecto.school.first_period == 0
    assert gpu.school.first_period == 0


def test_gpu001_identico_al_de_untis(sesion: UntisSession, tmp_path: Path) -> None:
    """El archivo que consume MiUntisWeb sale exactamente como lo escribe Untis."""
    SVC.export_gpu(sesion, tmp_path)
    assert _gpu_lines(tmp_path / "GPU001.TXT") == _gpu_lines(EXPORT / "GPU001.TXT")


def test_deseos_reales_de_gpu016(proyecto: UntisProject) -> None:
    deseos = proyecto.time_requests
    assert len(deseos) == 5582
    assert Counter(d.value for d in deseos) == {-3: 3930, 3: 1519, -1: 88, -2: 45}
    assert {d.entity_kind for d in deseos} == {
        EntityKind.CLASS,
        EntityKind.SUBJECT,
        EntityKind.TEACHER,
    }


def test_ida_y_vuelta_xml_gpu_rsp(proyecto: UntisProject, tmp_path: Path) -> None:
    write_xml(proyecto, tmp_path / "vuelta.xml")
    vuelta = read_xml(tmp_path / "vuelta.xml")
    assert vuelta.lessons == read_xml(XML).lessons
    save_rsp(proyecto, tmp_path / "p.rsp")
    assert load_rsp(tmp_path / "p.rsp") == proyecto
    write_gpu(proyecto, tmp_path / "gpu")
    de_gpu = read_gpu(tmp_path / "gpu")
    assert len(de_gpu.lessons) == len(proyecto.lessons)
    assert len(de_gpu.time_requests) == len(proyecto.time_requests)


def test_caracteres_raros_de_untis_se_conservan(proyecto: UntisProject, tmp_path: Path) -> None:
    """Untis escribe el byte 0x8D en algunos nombres; se lee y se reescribe igual."""
    raros = [t for t in proyecto.teachers if "\x8d" in t.forename]
    assert raros
    write_gpu(proyecto, tmp_path)
    assert b"\x8d" in (tmp_path / "GPU004.TXT").read_bytes()


# --------------------------------------------------------------------------- #
# El horario publicado por Untis, medido con nuestra vara
# --------------------------------------------------------------------------- #


def test_fidelidad_del_puente_con_el_horario_de_untis(proyecto: UntisProject) -> None:
    """Evaluador, `ValidationEngine` y reloj de pared ven los mismos choques."""
    rep = Evaluator(proyecto).report(proyecto.timetables[0])
    recursos = {c.entity_id for c in rep.clashes if c.kind in ("teacher", "class", "room")}
    # El horario publicado incumple 3 deseos -3 del propio colegio (lecciones
    # 2211 y 3035); se mide sin recortar esos dominios.
    vetos = sorted({n for c in rep.clashes if c.kind == "time_request" for n in c.lessons})
    assert vetos == [2211, 3035]
    tr = UntisTranslator(apply_blocks=False).translate(proyecto)
    rb = timetable_to_solution(tr, proyecto.timetables[0])
    assert rb.mismatched == ()
    informe = ValidationEngine().validate(tr.problem, rb.solution)
    assert {i.kind for i in informe.issues} <= {"capacity_exceeded"}
    nombre_de = {t.display_name: t.id for t in proyecto.teachers}
    nombre_de |= {c.display_name: c.id for c in proyecto.classes}
    nombre_de |= {r.display_name: r.id for r in proyecto.rooms}
    patron = re.compile(r"El recurso '(?P<res>.+)' aloja")
    motor = {nombre_de[m["res"]] for i in informe.issues if (m := patron.match(i.message))}
    assert motor == recursos


def test_reparar_el_horario_de_untis(proyecto: UntisProject) -> None:
    antes = Evaluator(proyecto).report(proyecto.timetables[0])
    out = repair(proyecto, proyecto.timetables[0], time_limit=30, include_unplaced=False)
    assert out.status in ("repaired", "nothing_to_do")
    despues = Evaluator(proyecto).report(out.timetable)
    duros = {"teacher", "class", "room"}
    assert not [c for c in despues.clashes if c.kind in duros]
    assert len(out.moved) <= max(10, 3 * len([c for c in antes.clashes if c.kind in duros]))


# --------------------------------------------------------------------------- #
# Generar desde cero con los datos reales
# --------------------------------------------------------------------------- #


def test_generar_desde_cero_respeta_los_deseos_y_no_choca(proyecto: UntisProject) -> None:
    """Sin el horario de Untis: se genera con la estrategia A y los deseos reales."""
    vacio = dataclasses.replace(proyecto, timetables=())
    s = UntisSession(vacio)
    t0 = time.perf_counter()
    out = SVC.optimize(s, OptimizeRequest(strategy="A", time_limit=45, polish=False))
    assert out.ok, out.message
    assert time.perf_counter() - t0 < 120  # criterio del documento maestro: A < 2 min
    tt = s.project.timetable_by_id(out.timetable_id)
    assert tt is not None
    rep = Evaluator(vacio).report(tt)
    assert rep.evaluation.clashes == 0  # sin choques y ningún deseo -3 incumplido
    sesiones = sum(le.periods_per_week for le in vacio.active_lessons)
    assert rep.evaluation.unplaced_periods <= 0.02 * sesiones  # criterio: <= 2 %


def test_generado_mejor_que_untis_con_la_misma_vara(proyecto: UntisProject) -> None:
    """Misma ponderación y mismos deseos: puntos blandos del generado frente a Untis."""
    untis = Evaluator(proyecto).evaluate(proyecto.timetables[0])
    s = UntisSession(dataclasses.replace(proyecto, timetables=()))
    out = SVC.optimize(s, OptimizeRequest(strategy="A", time_limit=45, polish=False))
    assert out.ok and out.evaluation is not None
    assert out.evaluation.clashes <= untis.clashes
    assert out.evaluation.soft_points < untis.soft_points


# --------------------------------------------------------------------------- #
# Una sección entera tecleada desde cero con la Fachada (como el usuario)
# --------------------------------------------------------------------------- #


def test_seccion_tecleada_desde_cero_y_generada(proyecto: UntisProject) -> None:
    """Se vuelve a introducir la sección Primaria —rejilla, clases, profesores,
    materias, aulas, lecciones con sus acoples y deseos— solo con la Fachada, se
    genera y se obtienen los horarios de cada clase y profesor."""
    rejilla = proyecto.grid_by_id["Primaria"]
    clases = [c for c in proyecto.classes if c.time_grid == "Primaria"]
    ids_clase = {c.id for c in clases}
    lecciones = [
        le
        for le in proyecto.active_lessons
        if le.time_grid == "Primaria" and le.classes and set(le.classes) <= ids_clase
    ]
    assert len(clases) >= 10 and len(lecciones) >= 50

    s = SVC.new("Primaria desde cero", default_grid=False)
    lectivos = [p for p in rejilla.periods if p.is_teaching]
    recreos = {
        sum(1 for q in lectivos if q.number < p.number): p.duration
        for p in rejilla.periods
        if not p.is_teaching and any(q.number < p.number for q in lectivos)
    }
    duracion = Counter(p.duration for p in lectivos).most_common(1)[0][0]
    assert SVC.add_grid(
        s,
        "Primaria",
        days=rejilla.days,
        periods=len(lectivos),
        start=f"{lectivos[0].start // 60:02d}:{lectivos[0].start % 60:02d}",
        duration=duracion,
        gap=0,
        breaks={k: v for k, v in recreos.items() if 0 < k < len(lectivos)},
    ).ok

    profes = sorted({t for le in lecciones for t in le.teachers})
    materias = sorted({ln.subject for le in lecciones for ln in le.lines})
    for c in clases:
        assert SVC.add_master(s, MasterKind.CLASSES, c.id).ok
    for t in profes:
        assert SVC.add_master(s, MasterKind.TEACHERS, t).ok
    for m in materias:
        assert SVC.add_master(s, MasterKind.SUBJECTS, m).ok

    for le in lecciones:
        primera = le.lines[0]
        r = SVC.add_lesson(
            s,
            subject=primera.subject,
            teacher=primera.teacher,
            classes=primera.classes or le.classes,
            periods=le.periods_per_week,
        )
        assert r.ok, r.message
        numero = int(r.message)
        for i, linea in enumerate(le.lines[1:], start=1):
            assert SVC.add_line(s, numero).ok
            assert SVC.set_line_field(s, numero, i, "subject", linea.subject).ok
            assert SVC.set_line_field(s, numero, i, "teacher", linea.teacher or "").ok
            assert SVC.set_line_field(s, numero, i, "classes", ", ".join(linea.classes)).ok
        if le.double_periods.is_set:
            rango = f"{le.double_periods.min or ''}-{le.double_periods.max or ''}"
            assert SVC.set_lesson_field(s, numero, "double_periods", rango).ok

    for d in proyecto.time_requests:
        dueno = {EntityKind.CLASS: ids_clase, EntityKind.TEACHER: set(profes)}.get(
            d.entity_kind, set()
        )
        if d.entity_id in dueno and d.value == -3:
            kind = "class" if d.entity_kind is EntityKind.CLASS else "teacher"
            assert SVC.set_request(s, kind, d.entity_id, d.day, d.period, d.value).ok

    assert [i for i in SVC.diagnosis(s).items if i.severity == "error"] == []
    out = SVC.optimize(s, OptimizeRequest(strategy="A", time_limit=20, polish=False))
    assert out.ok, out.message
    assert out.evaluation is not None and out.evaluation.clashes == 0
    total = sum(le.periods_per_week for le in lecciones)
    assert out.evaluation.unplaced_periods <= 0.02 * total
    for c in clases:
        assert SVC.timetable_grid(s, "class", c.id).cells
    assert all(SVC.timetable_grid(s, "teacher", t).cells for t in profes[:10])
