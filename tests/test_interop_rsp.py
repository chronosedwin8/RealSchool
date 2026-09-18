"""Formato `.rsp`: ida y vuelta, determinismo, integridad, versiones y atomicidad."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings

from scheduling_platform.interop import rsp
from scheduling_platform.interop.codec import JsonObject, JsonValue
from scheduling_platform.interop.rsp import (
    FORMAT_NAME,
    FORMAT_VERSION,
    MANIFEST,
    RspChecksumError,
    RspError,
    RspVersionError,
    load_rsp,
    read_rsp_entries,
    register_migration,
    save_rsp,
)
from scheduling_platform.untis_model import (
    Assignment,
    CriterionScore,
    DateScheme,
    Department,
    EntityKind,
    Evaluation,
    HalfDay,
    Lesson,
    LessonLine,
    MinMax,
    PeriodDef,
    PeriodKind,
    Room,
    SchoolClass,
    SchoolInfo,
    StudentGroup,
    Subject,
    Teacher,
    Term,
    TimeGrid,
    TimeRequest,
    Timetable,
    UnspecifiedKind,
    UnspecifiedRequest,
    UntisProject,
    Weighting,
)

from .test_interop_codec import untis_projects

T0 = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
T1 = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)


def _rich_project() -> UntisProject:
    grid = TimeGrid(
        id="G1",
        name="Primaria",
        days=(1, 2, 3, 4, 5),
        periods=(
            PeriodDef(1, 7 * 60 + 30, 8 * 60 + 15),
            PeriodDef(2, 8 * 60 + 15, 8 * 60 + 30, kind=PeriodKind.BREAK, name="Recreo"),
            PeriodDef(3, 13 * 60, 13 * 60 + 45, half_day=HalfDay.AFTERNOON),
        ),
    )
    return UntisProject(
        school=SchoolInfo(name="Colegio Ñandú", school_year_begin="20260801", term_name="S1"),
        time_grids=(grid, TimeGrid(id="G2")),
        departments=(Department("CIE", "Ciencias"),),
        classes=(
            SchoolClass(
                "5A",
                "Quinto A",
                time_grid="G1",
                home_room="R1",
                department="CIE",
                students=28,
                level=5,
                periods_per_day=MinMax(4, 7),
                lunch_break=MinMax(1, None),
                main_subjects_per_day=2,
            ),
        ),
        teachers=(
            Teacher(
                "ANA",
                surname="Pérez",
                forename="Ana",
                email="ana@example.org",
                ntp_per_week=MinMax(None, 4),
                consecutive_max=4,
            ),
            Teacher("BEN"),
        ),
        rooms=(Room("R1", capacity=30, alternative_room="R2", room_weight=3), Room("R2")),
        subjects=(Subject("MA", "Matemáticas", main_subject=True), Subject("IB")),
        student_groups=(StudentGroup("IB-HL", subject="IB", classes=("5A",), students=12),),
        terms=(Term("T1", begin="20260801", end="20261220", time_grid="G1"),),
        lessons=(
            Lesson(1, (LessonLine("MA", "ANA", ("5A",), room="R1", weekly_value=4.5),), 4, "G1"),
            Lesson(
                2,
                (
                    LessonLine("IB", "ANA", ("5A",), student_group="IB-HL"),
                    LessonLine("IB", None, ("5A",), alternative_room="R2"),
                ),
                2,
                block=(2, 2),
                double_periods=MinMax(1, 1),
                sequence_after="MA",
                term="T1",
            ),
        ),
        time_requests=(
            TimeRequest(EntityKind.TEACHER, "ANA", -3, day=1),
            TimeRequest(EntityKind.ROOM, "R1", 2, period=3),
        ),
        unspecified_requests=(
            UnspecifiedRequest(EntityKind.TEACHER, "BEN", UnspecifiedKind.FREE_AFTERNOON, 2),
        ),
        weighting=Weighting(teacher_gaps=5, class_gaps=1),
        timetables=(
            Timetable(
                "V1",
                "Versión 1",
                (Assignment(1, 0, 1, 1, room="R1", fixed=True), Assignment(2, 1, 2, 3)),
                Evaluation(1, 0, (CriterionScore("teacher_gaps", 3, 300),)),
            ),
            Timetable("V2/borrador"),
        ),
        date_schemes=(DateScheme(".", "11111FF11111FF", "1"),),
    )


def _entries(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


def _write(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for nombre, data in files.items():
            archive.writestr(nombre, data)


def _json_bytes(doc: JsonValue) -> bytes:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def _manifest(files: dict[str, bytes]) -> JsonObject:
    doc = json.loads(files[MANIFEST])
    assert isinstance(doc, dict)
    return doc


def _rewrite(
    path: Path,
    mutate: Callable[[JsonObject, dict[str, bytes]], None],
    *,
    rehash: bool = True,
) -> None:
    """Reescribe el `.rsp`: `mutate` edita manifiesto y entradas; recalcula checksums."""
    files = _entries(path)
    manifest = _manifest(files)
    del files[MANIFEST]
    mutate(manifest, files)
    if rehash:
        manifest["checksums"] = {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}
    _write(path, {MANIFEST: _json_bytes(manifest), **files})


@pytest.fixture
def clean_migrations(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(rsp, "_MIGRATIONS", {})
    yield


# --------------------------------------------------------------------------- #
# Ida y vuelta
# --------------------------------------------------------------------------- #


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(untis_projects)
def test_ida_y_vuelta_hypothesis(project: UntisProject) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "p.rsp"
        save_rsp(project, path)
        assert load_rsp(path) == project


def test_ida_y_vuelta_proyecto_rico(tmp_path: Path) -> None:
    project = _rich_project()
    path = tmp_path / "rico.rsp"
    save_rsp(project, path)
    assert load_rsp(path) == project


def test_estructura_del_archivo_y_manifiesto(tmp_path: Path) -> None:
    path = tmp_path / "rico.rsp"
    save_rsp(_rich_project(), path, now=T1, created=T0)
    files = _entries(path)
    nombres = list(files)
    assert nombres[0] == MANIFEST
    for seccion in (
        "school",
        "time_grids",
        "lessons",
        "weighting",
        "time_requests",
        "date_schemes",
    ):
        assert f"{seccion}.json" in files
    horarios = [n for n in nombres if n.startswith("timetables/")]
    assert len(horarios) == 2

    manifest = _manifest(files)
    assert manifest["format"] == FORMAT_NAME
    assert manifest["format_version"] == FORMAT_VERSION
    assert manifest["created"] == "2026-09-01T08:00:00+00:00"
    assert manifest["modified"] == "2026-09-02T09:30:00+00:00"
    assert isinstance(manifest["app_version"], str)
    orden = manifest["timetables"]
    assert isinstance(orden, list)
    assert set(orden) == set(horarios)
    checksums = manifest["checksums"]
    assert isinstance(checksums, dict)
    assert set(checksums) == set(nombres) - {MANIFEST}
    for nombre, digest in checksums.items():
        assert hashlib.sha256(files[nombre]).hexdigest() == digest
    # JSON canónico: UTF-8 sin escapar y claves ordenadas.
    assert "Ñandú".encode() in files["school.json"]


def test_orden_de_horarios_se_conserva(tmp_path: Path) -> None:
    # "a/b" y "a b" dan el mismo slug; el hash del id los separa.
    tts = tuple(Timetable(i) for i in ("z", "a/b", "m", "a b"))
    project = UntisProject(timetables=tts)
    path = tmp_path / "o.rsp"
    save_rsp(project, path)
    assert load_rsp(path).timetables == tts
    assert len({n for n in _entries(path) if n.startswith("timetables/")}) == 4


# --------------------------------------------------------------------------- #
# Determinismo y sellos de tiempo
# --------------------------------------------------------------------------- #


def test_determinista_byte_a_byte(tmp_path: Path) -> None:
    a, b = tmp_path / "a.rsp", tmp_path / "b.rsp"
    save_rsp(_rich_project(), a, now=T1, created=T0)
    save_rsp(_rich_project(), b, now=T1, created=T0)
    assert a.read_bytes() == b.read_bytes()


def test_solo_el_manifiesto_cambia_con_la_hora(tmp_path: Path) -> None:
    a, b = tmp_path / "a.rsp", tmp_path / "b.rsp"
    save_rsp(_rich_project(), a, now=T0, created=T0)
    save_rsp(_rich_project(), b, now=T1, created=T0)
    fa, fb = _entries(a), _entries(b)
    assert {n for n in fa if fa[n] != fb[n]} == {MANIFEST}


def test_created_se_conserva_al_regrabar(tmp_path: Path) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(UntisProject(), path, now=T0)
    save_rsp(UntisProject(school=SchoolInfo(name="X")), path, now=T1)
    manifest = _manifest(_entries(path))
    assert manifest["created"] == "2026-09-01T08:00:00+00:00"
    assert manifest["modified"] == "2026-09-02T09:30:00+00:00"


# --------------------------------------------------------------------------- #
# Integridad
# --------------------------------------------------------------------------- #


def test_manipulacion_detectada(tmp_path: Path) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(_rich_project(), path)

    def tamper(_m: JsonObject, files: dict[str, bytes]) -> None:
        files["lessons.json"] = files["lessons.json"].replace(b'"ANA"', b'"EVE"')

    _rewrite(path, tamper, rehash=False)
    with pytest.raises(RspChecksumError, match=r"lessons\.json"):
        load_rsp(path)


def test_entrada_declarada_ausente(tmp_path: Path) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(_rich_project(), path)

    def quitar(_m: JsonObject, files: dict[str, bytes]) -> None:
        del files["teachers.json"]

    _rewrite(path, quitar, rehash=False)
    with pytest.raises(RspChecksumError, match=r"teachers\.json"):
        load_rsp(path)


def test_entrada_conocida_sin_checksum(tmp_path: Path) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(UntisProject(), path)

    def colar(_m: JsonObject, files: dict[str, bytes]) -> None:
        files["timetables/colado.json"] = _json_bytes({"id": "X"})

    _rewrite(path, colar, rehash=False)
    with pytest.raises(RspChecksumError, match="colado"):
        load_rsp(path)


@pytest.mark.parametrize(
    ("contenido", "mensaje"),
    [
        (b"no soy un zip", "no es un archivo .rsp"),
        (None, "falta manifest.json"),
    ],
)
def test_archivo_invalido(tmp_path: Path, contenido: bytes | None, mensaje: str) -> None:
    path = tmp_path / "x.rsp"
    if contenido is None:
        _write(path, {"school.json": b"{}"})
    else:
        path.write_bytes(contenido)
    with pytest.raises(RspError, match=mensaje):
        load_rsp(path)


def test_firma_ajena(tmp_path: Path) -> None:
    path = tmp_path / "x.rsp"
    save_rsp(UntisProject(), path)
    _rewrite(path, lambda m, _f: m.update(format="otra-cosa"))
    with pytest.raises(RspError, match="no es un proyecto RealSchool"):
        load_rsp(path)


def test_no_existe(tmp_path: Path) -> None:
    with pytest.raises(RspError, match="no existe"):
        load_rsp(tmp_path / "nada.rsp")


# --------------------------------------------------------------------------- #
# Compatibilidad y versiones
# --------------------------------------------------------------------------- #


def test_entrada_y_claves_desconocidas_se_ignoran(tmp_path: Path) -> None:
    project = _rich_project()
    path = tmp_path / "p.rsp"
    save_rsp(project, path)

    def extender(m: JsonObject, files: dict[str, bytes]) -> None:
        m["campo_futuro"] = {"x": 1}
        files["plugins_futuros.json"] = _json_bytes({"loquesea": [1, 2]})
        profes = json.loads(files["teachers.json"])
        for profe in profes:
            profe["color"] = "#ff0000"
        files["teachers.json"] = _json_bytes(profes)

    _rewrite(path, extender)
    assert load_rsp(path) == project


def test_entrada_sin_declarar_se_ignora(tmp_path: Path) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(UntisProject(), path)
    _rewrite(path, lambda _m, f: f.update({"extra/nota.txt": b"hola"}), rehash=False)
    assert load_rsp(path) == UntisProject()


def test_secciones_ausentes_toman_valor_por_defecto(tmp_path: Path) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(_rich_project(), path)

    def podar(m: JsonObject, files: dict[str, bytes]) -> None:
        for nombre in list(files):
            if nombre != "teachers.json":
                del files[nombre]
        m["timetables"] = []

    _rewrite(path, podar)
    assert load_rsp(path) == UntisProject(teachers=_rich_project().teachers)


def test_version_mayor_futura_rechazada(tmp_path: Path) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(UntisProject(), path)
    _rewrite(path, lambda m, _f: m.update(format_version="2.0.0"))
    with pytest.raises(RspVersionError, match=r"2\.0\.0.*más nuevo"):
        load_rsp(path)


def test_version_menor_futura_aceptada(tmp_path: Path) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(_rich_project(), path)
    _rewrite(path, lambda m, _f: m.update(format_version="1.7.3"))
    assert load_rsp(path) == _rich_project()


def test_version_mal_formada(tmp_path: Path) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(UntisProject(), path)
    _rewrite(path, lambda m, _f: m.update(format_version="uno"))
    with pytest.raises(RspVersionError, match="inválida"):
        load_rsp(path)


def _escribir_v0(path: Path) -> None:
    """Simula un `.rsp` 0.9.0: las lecciones llamaban `hours` a `periods_per_week`."""
    save_rsp(_rich_project(), path)

    def degradar(m: JsonObject, files: dict[str, bytes]) -> None:
        m["format_version"] = "0.9.0"
        lecciones = json.loads(files["lessons.json"])
        for le in lecciones:
            le["hours"] = le.pop("periods_per_week")
        files["lessons.json"] = _json_bytes(lecciones)

    _rewrite(path, degradar)


@pytest.mark.usefixtures("clean_migrations")
def test_sin_migracion_la_version_antigua_se_rechaza(tmp_path: Path) -> None:
    path = tmp_path / "v0.rsp"
    _escribir_v0(path)
    with pytest.raises(RspVersionError, match="no hay ruta de migración"):
        load_rsp(path)


@pytest.mark.usefixtures("clean_migrations")
def test_migracion_en_cadena(tmp_path: Path) -> None:
    path = tmp_path / "v0.rsp"
    _escribir_v0(path)
    pasos: list[str] = []

    def v09_a_v095(
        manifest: JsonObject, entries: dict[str, JsonValue]
    ) -> tuple[JsonObject, dict[str, JsonValue]]:
        pasos.append("0.9.0")
        lecciones = entries["lessons.json"]
        assert isinstance(lecciones, list)
        for le in lecciones:
            assert isinstance(le, dict)
            le["periods_per_week"] = le.pop("hours")
        return manifest, entries

    def v095_a_v1(
        manifest: JsonObject, entries: dict[str, JsonValue]
    ) -> tuple[JsonObject, dict[str, JsonValue]]:
        pasos.append("0.9.5")
        return manifest, entries

    register_migration("0.9.0", "0.9.5", v09_a_v095)
    register_migration("0.9.5", FORMAT_VERSION, v095_a_v1)
    assert load_rsp(path) == _rich_project()
    assert pasos == ["0.9.0", "0.9.5"]
    manifest, _ = read_rsp_entries(path)
    assert manifest["format_version"] == FORMAT_VERSION


# --------------------------------------------------------------------------- #
# Escritura atómica
# --------------------------------------------------------------------------- #


def test_escritura_atomica_no_deja_temporales(tmp_path: Path) -> None:
    save_rsp(_rich_project(), tmp_path / "p.rsp")
    save_rsp(_rich_project(), tmp_path / "p.rsp")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.rsp"]


def test_fallo_al_renombrar_conserva_el_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "p.rsp"
    save_rsp(_rich_project(), path)
    original = path.read_bytes()

    def falla(_src: object, _dst: object) -> None:
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", falla)
    with pytest.raises(RspError, match="disco lleno"):
        save_rsp(UntisProject(), path)
    assert path.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.rsp"]


def test_valor_no_json_falla_antes_de_tocar_disco(tmp_path: Path) -> None:
    project = UntisProject(lessons=(Lesson(1, (LessonLine("MA", weekly_value=float("nan")),), 1),))
    path = tmp_path / "p.rsp"
    with pytest.raises(RspError, match="JSON"):
        save_rsp(project, path)
    assert not any(tmp_path.iterdir())


# --------------------------------------------------------------------------- #
# Export real seudonimizado
# --------------------------------------------------------------------------- #


def test_xml_anonimo_ida_y_vuelta(anon_xml_path: Path, tmp_path: Path) -> None:
    xml = pytest.importorskip("scheduling_platform.interop.xml")
    project: UntisProject = xml.read_xml(anon_xml_path)
    assert len(project.lessons) == 722
    path = tmp_path / "anon.rsp"
    save_rsp(project, path, now=T0, created=T0)
    assert load_rsp(path) == project
    otra = tmp_path / "anon2.rsp"
    save_rsp(load_rsp(path), otra, now=T0, created=T0)
    assert otra.read_bytes() == path.read_bytes()
