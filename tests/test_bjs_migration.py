"""Seam de migración de esquemas .bjs (B5): upcast encadenado en memoria."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scheduling_platform.serialization import UnsupportedSchemaVersion
from scheduling_platform.serialization.bjs import (
    FORMAT_VERSION,
    Migration,
    build_manifest,
    migrate,
    pack,
    read,
    register_migration,
)

Doc = dict[str, Any]


def _manifest(version: str) -> Doc:
    m = build_manifest(project_name="Demo", engine_signature={})
    m["format_version"] = version
    return m


def test_migrate_es_no_op_en_la_version_actual() -> None:
    manifest = _manifest(FORMAT_VERSION)
    entries = {"a.json": {"x": 1}}
    out_m, out_e = migrate(manifest, entries)
    assert out_m["format_version"] == FORMAT_VERSION
    assert out_e == entries


def test_migracion_encadenada_con_registro_propio() -> None:
    def v08_to_v09(m: Doc, e: dict[str, Doc]) -> tuple[Doc, dict[str, Doc]]:
        return m, {**e, "paso1": {"ok": True}}

    def v09_to_v10(m: Doc, e: dict[str, Doc]) -> tuple[Doc, dict[str, Doc]]:
        return m, {**e, "paso2": {"ok": True}}

    registry: dict[tuple[str, str], Migration] = {
        ("0.8.0", "0.9.0"): v08_to_v09,
        ("0.9.0", FORMAT_VERSION): v09_to_v10,
    }
    manifest, entries = migrate(_manifest("0.8.0"), {"base": {}}, migrations=registry)
    assert manifest["format_version"] == FORMAT_VERSION
    assert "paso1" in entries and "paso2" in entries  # ambas migraciones se aplicaron


def test_version_sin_ruta_falla() -> None:
    with pytest.raises(UnsupportedSchemaVersion, match="no soportada"):
        migrate(_manifest("9.9.9"), {}, migrations={})


@pytest.fixture
def _registered_migration() -> Iterator[None]:
    def upcast(m: Doc, e: dict[str, Doc]) -> tuple[Doc, dict[str, Doc]]:
        return m, {**e, "migrado.json": {"desde": "0.9.0"}}

    register_migration("0.9.0", FORMAT_VERSION, upcast)
    try:
        yield
    finally:
        from scheduling_platform.serialization.bjs import _MIGRATIONS

        _MIGRATIONS.pop(("0.9.0", FORMAT_VERSION), None)


def test_read_aplica_la_migracion_registrada(tmp_path: Path, _registered_migration: None) -> None:
    path = tmp_path / "viejo.bjs"
    pack(path, {"resources.json": {"resources": []}}, _manifest("0.9.0"))
    manifest, entries = read(path)
    assert manifest["format_version"] == FORMAT_VERSION  # upcast al leer
    assert "migrado.json" in entries
