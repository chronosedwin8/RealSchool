"""Contenedor crudo .bjs (B1): round-trip, integridad, determinismo, atomicidad."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from scheduling_platform.serialization import UnsupportedSchemaVersion
from scheduling_platform.serialization.bjs import (
    MANIFEST,
    BjsChecksumError,
    BjsError,
    build_manifest,
    extract,
    pack,
    pack_dir,
    read,
)

_SIG = {"engine_version": "0.1.0", "git_commit": "abc1234"}
_ENTRIES: dict[str, dict[str, Any]] = {
    "resources.json": {"resources": [{"id": 0, "tags": ["teacher"]}]},
    "tasks.json": {"tasks": [{"id": 0, "duration": 1}]},
}


def _manifest() -> dict[str, Any]:
    return build_manifest(project_name="Demo", engine_signature=_SIG)


def test_pack_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    pack(path, _ENTRIES, _manifest())
    manifest, entries = read(path)
    assert manifest["project_name"] == "Demo"
    assert manifest["engine_signature"] == _SIG
    assert entries == _ENTRIES
    assert set(manifest["checksums"]) == set(_ENTRIES)  # un checksum por entrada


def test_checksum_detecta_manipulacion(tmp_path: Path) -> None:
    path = tmp_path / "bad.bjs"
    manifest = _manifest()
    manifest["checksums"] = {"a.json": "deadbeef"}  # checksum que no cuadra
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(MANIFEST, json.dumps(manifest))
        archive.writestr("a.json", json.dumps({"x": 1}))
    path.write_bytes(buffer.getvalue())
    with pytest.raises(BjsChecksumError):
        read(path)


def test_json_interno_malformado_falla_claro(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.bjs"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(MANIFEST, json.dumps(_manifest()))  # checksums vacíos
        archive.writestr("roto.json", b"esto no es json{")
    path.write_bytes(buffer.getvalue())
    with pytest.raises(BjsError, match="JSON inválido"):
        read(path)


def test_version_no_soportada_falla(tmp_path: Path) -> None:
    path = tmp_path / "v9.bjs"
    manifest = _manifest()
    manifest["format_version"] = "9.9.9"
    pack(path, {}, manifest)
    with pytest.raises(UnsupportedSchemaVersion, match="no soportada"):
        read(path)


def test_archivo_no_zip_falla(tmp_path: Path) -> None:
    no_zip = tmp_path / "x.bjs"
    no_zip.write_text("no soy un zip", encoding="utf-8")
    with pytest.raises(BjsError, match="válido"):
        read(no_zip)


def test_archivo_inexistente_falla(tmp_path: Path) -> None:
    with pytest.raises(BjsError, match="no existe"):
        read(tmp_path / "fantasma.bjs")


def test_extract_es_determinista_y_git_friendly(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    pack(path, _ENTRIES, _manifest())
    a = extract(path, tmp_path / "a")
    extract(path, tmp_path / "b")
    # dos extract producen bytes idénticos (sort_keys + indent 2)
    for pa in a:
        pb = tmp_path / "b" / pa.relative_to(tmp_path / "a")
        assert pa.read_bytes() == pb.read_bytes()
    contenido = (tmp_path / "a" / "resources.json").read_text(encoding="utf-8")
    assert contenido.startswith("{\n")  # indentado, legible para diffs


def test_extract_editar_pack_dir_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    pack(path, _ENTRIES, _manifest())
    extract(path, tmp_path / "src")
    # editar un JSON extraído
    tasks = tmp_path / "src" / "tasks.json"
    doc = json.loads(tasks.read_text(encoding="utf-8"))
    doc["tasks"].append({"id": 1, "duration": 2})
    tasks.write_text(json.dumps(doc), encoding="utf-8")
    # re-empaquetar y releer
    nuevo = tmp_path / "nuevo.bjs"
    pack_dir(tmp_path / "src", nuevo)
    _, entries = read(nuevo)
    assert len(entries["tasks.json"]["tasks"]) == 2


def test_escritura_atomica_no_corrompe_ante_fallo(tmp_path: Path) -> None:
    path = tmp_path / "p.bjs"
    pack(path, _ENTRIES, _manifest())
    original = path.read_bytes()
    # una entrada no serializable hace fallar el pack ANTES de tocar el disco
    malo: dict[str, Any] = {"malo.json": {"x": object()}}
    with pytest.raises(TypeError):
        pack(path, malo, _manifest())
    assert path.read_bytes() == original  # intacto
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*tmp*")) == []
