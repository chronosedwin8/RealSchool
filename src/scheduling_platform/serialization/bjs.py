"""Contenedor crudo ``.bjs`` (Fase 3, B1): ZIP multi-archivo, íntegro y atómico.

Un ``.bjs`` es un ZIP (DEFLATE) con un ``manifest.json`` (firma, versión, sellos
de tiempo y **checksums SHA-256** por archivo) y varios JSON aislados por concern.
Esta capa es **agnóstica del dominio y de la config**: opera sobre dicts crudos,
por lo que vive en el Core (``serialization``) sin importar la capa de aplicación.
La interpretación tipada (canónico + config) la hace ``application`` (B2).

Garantías:
- **Escritura atómica**: se serializa en memoria y se renombra con ``os.replace``
  (un corte de energía nunca deja un ``.bjs`` a medio escribir).
- **Integridad**: al leer se verifican los checksums; un archivo manipulado falla.
- **Git-friendly**: ``extract`` escribe cada JSON con ``sort_keys`` e indent 2,
  de forma determinista (dos extract del mismo ``.bjs`` son byte-idénticos).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import uuid as uuidlib
import zipfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .codec import Doc
from .exceptions import SerializationError, UnsupportedSchemaVersion

FORMAT_VERSION = "1.0.0"
MANIFEST = "manifest.json"

#: Una migración transforma ``(manifest, entries)`` de una versión a la siguiente.
Migration = Callable[[Doc, dict[str, Doc]], tuple[Doc, dict[str, Doc]]]

#: Registro de migraciones ``(desde, hasta) -> transform``. Vacío en v1 (no-op).
_MIGRATIONS: dict[tuple[str, str], Migration] = {}


class BjsError(SerializationError):
    """Error del contenedor ``.bjs`` (formato, E/S o integridad)."""


class BjsChecksumError(BjsError):
    """Un archivo interno no coincide con su checksum: contenido manipulado."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _canonical_bytes(doc: Doc) -> bytes:
    """JSON determinista (sort_keys, indent 2): base de checksums y de diffs Git."""
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(
    *,
    project_name: str,
    engine_signature: Mapping[str, Any],
    uuid: str | None = None,
    created: str | None = None,
    format_version: str = FORMAT_VERSION,
) -> Doc:
    """Construye un ``manifest`` (sin checksums; se rellenan en ``pack``)."""
    now = _now()
    return {
        "project_name": project_name,
        "uuid": uuid or str(uuidlib.uuid4()),
        "format_version": format_version,
        "engine_signature": dict(engine_signature),
        "timestamps": {"created": created or now, "modified": now},
        "checksums": {},
    }


def register_migration(from_version: str, to_version: str, transform: Migration) -> None:
    """Registra una migración de esquema ``from_version -> to_version`` (upcast)."""
    _MIGRATIONS[(from_version, to_version)] = transform


def migrate(
    manifest: Doc,
    entries: dict[str, Doc],
    *,
    migrations: Mapping[tuple[str, str], Migration] | None = None,
) -> tuple[Doc, dict[str, Doc]]:
    """Lleva ``(manifest, entries)`` a :data:`FORMAT_VERSION` aplicando migraciones en cadena.

    Si la versión ya es la actual, es un no-op. Si no hay ruta de migración, falla
    con un mensaje claro (formato durará décadas: el mecanismo queda listo aunque
    v1 no tenga aún ninguna migración registrada).
    """
    registry = migrations if migrations is not None else _MIGRATIONS
    version = str(manifest.get("format_version", ""))
    seen: set[str] = set()
    while version != FORMAT_VERSION:
        if version in seen:  # pragma: no cover - registro mal formado
            raise BjsError(f"ciclo de migración detectado en la versión {version!r}")
        seen.add(version)
        target = next((t for (frm, t) in registry if frm == version), None)
        if target is None:
            raise UnsupportedSchemaVersion(
                f"versión .bjs no soportada: {version!r} "
                f"(sin ruta de migración hasta {FORMAT_VERSION})"
            )
        manifest, entries = registry[(version, target)](manifest, entries)
        manifest = {**manifest, "format_version": target}
        version = target
    return manifest, entries


def _atomic_write(target: Path, data: bytes) -> None:
    tmp = target.with_name(f".{target.name}.{uuidlib.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    except OSError as exc:  # pragma: no cover - E/S del sistema
        tmp.unlink(missing_ok=True)
        raise BjsError(f"no se pudo escribir {target}: {exc}") from exc


def pack(path: str | Path, entries: Mapping[str, Doc], manifest: Doc) -> None:
    """Empaqueta ``entries`` + ``manifest`` en un ``.bjs`` de forma atómica.

    Calcula los checksums sobre los bytes canónicos de cada entrada y actualiza el
    sello ``modified``. Si alguna entrada no es serializable, falla **antes** de
    tocar el disco (el ``.bjs`` original nunca queda corrupto).
    """
    serialized = {name: _canonical_bytes(doc) for name, doc in entries.items()}
    checksums = {name: _sha256(data) for name, data in serialized.items()}
    full_manifest = {
        **manifest,
        "checksums": checksums,
        "timestamps": {**manifest.get("timestamps", {}), "modified": _now()},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, _canonical_bytes(full_manifest))
        for name, data in serialized.items():
            archive.writestr(name, data)
    _atomic_write(Path(path), buffer.getvalue())


def read(path: str | Path) -> tuple[Doc, dict[str, Doc]]:
    """Lee un ``.bjs`` en memoria, verifica versión e integridad. Devuelve (manifest, entradas)."""
    target = Path(path)
    if not target.exists():
        raise BjsError(f"no existe el .bjs: {target}")
    try:
        raw = target.read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = set(archive.namelist())
            if MANIFEST not in names:
                raise BjsError(f"{target} no es un .bjs válido (falta {MANIFEST})")
            manifest = json.loads(archive.read(MANIFEST))
            checksums = manifest.get("checksums", {})
            entries: dict[str, Doc] = {}
            for name in sorted(names):
                if name == MANIFEST:
                    continue
                data = archive.read(name)
                expected = checksums.get(name)
                if expected is not None and _sha256(data) != expected:
                    raise BjsChecksumError(
                        f"checksum no coincide para {name!r} (archivo manipulado o corrupto)"
                    )
                entries[name] = json.loads(data)
    except zipfile.BadZipFile as exc:
        raise BjsError(f"{target} no es un archivo .bjs válido: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BjsError(f"JSON inválido dentro de {target}: {exc}") from exc
    # Upcast en memoria a la versión actual (no-op si ya lo está).
    return migrate(manifest, entries)


def extract(path: str | Path, out_dir: str | Path) -> list[Path]:
    """Descomprime a ``out_dir`` con JSON git-friendly (sort_keys, indent 2)."""
    manifest, entries = read(path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = [out / MANIFEST]
    (out / MANIFEST).write_bytes(_canonical_bytes(manifest))
    for name, doc in entries.items():
        dest = out / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_canonical_bytes(doc))
        written.append(dest)
    return written


def pack_dir(src_dir: str | Path, path: str | Path) -> None:
    """Re-empaqueta un directorio extraído (recomputa checksums e injecta manifest)."""
    src = Path(src_dir)
    manifest_path = src / MANIFEST
    if not manifest_path.exists():
        raise BjsError(f"falta {MANIFEST} en {src}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries: dict[str, Doc] = {}
    for candidate in sorted(src.rglob("*.json")):
        rel = candidate.relative_to(src).as_posix()
        if rel == MANIFEST:
            continue
        entries[rel] = json.loads(candidate.read_text(encoding="utf-8"))
    pack(path, entries, manifest)
