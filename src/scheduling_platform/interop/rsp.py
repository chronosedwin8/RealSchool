"""Formato de proyecto nativo `.rsp`: ZIP con un JSON por entidad + `manifest.json`.

Sustituye al `.bjs` + `schoolweeks.json` heredados (`REFACTOR_UNTIS_MAESTRO.md`,
secciones 4 y 9). Reutiliza las ideas del contenedor `serialization/bjs.py`
(checksums, escritura atómica, migraciones en cadena) pero **no lo importa**:
aquel depende de `serialization.codec`, que importa `core`, y la capa `interop`
solo conoce `untis_model`.

Estructura del archivo (todas las entradas en JSON UTF-8)::

    manifest.json            firma, versión, sellos de tiempo, checksums
    school.json              SchoolInfo
    time_grids.json          [TimeGrid]
    departments.json         [Department]
    classes.json             [SchoolClass]
    teachers.json            [Teacher]
    rooms.json               [Room]
    subjects.json            [Subject]
    student_groups.json      [StudentGroup]
    terms.json               [Term]
    lessons.json             [Lesson]
    time_requests.json       [TimeRequest]
    unspecified_requests.json [UnspecifiedRequest]
    weighting.json           Weighting
    date_schemes.json        [DateScheme]
    timetables/<slug>.json   un Timetable por versión de horario

Los horarios van **uno por archivo**: son la parte más voluminosa, cambian por
separado (cada optimización añade o reemplaza una versión) y así un diff de Git
o una carga parcial solo tocan la versión afectada. Su orden vive en
`manifest["timetables"]`, de modo que el nombre del archivo no necesita número de
orden (borrar una versión no renombra las demás).

Garantías:

- **Determinista**: JSON canónico (claves ordenadas, indent 2, UTF-8 sin escapar)
  y entradas ZIP con fecha fija y orden fijo. El mismo proyecto con los mismos
  sellos de tiempo produce un archivo byte-idéntico.
- **Íntegro**: el manifiesto guarda el SHA-256 de cada entrada; al leer, una
  entrada alterada lanza `RspChecksumError`.
- **Atómico**: se escribe en un temporal del mismo directorio y se renombra con
  `os.replace`; un fallo nunca deja un `.rsp` a medio escribir.
- **Versionado**: `format_version` semver. Las versiones anteriores se elevan con
  migraciones registradas (`register_migration`); una versión mayor más nueva
  que la soportada se rechaza con `RspVersionError`. Las entradas y claves
  desconocidas se ignoran (compatibilidad hacia delante).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import uuid
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Final

from ..untis_model import UntisProject
from .codec import PROJECT_SECTIONS, JsonObject, JsonValue, project_from_dict, project_to_dict

__all__ = [
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "MANIFEST",
    "Migration",
    "RspChecksumError",
    "RspError",
    "RspVersionError",
    "load_rsp",
    "migrate",
    "read_rsp_entries",
    "register_migration",
    "save_rsp",
]

#: Firma del formato en el manifiesto.
FORMAT_NAME: Final = "realschool-project"
#: Versión del formato que escribe este código (semver).
FORMAT_VERSION: Final = "1.0.0"
MANIFEST: Final = "manifest.json"
_TIMETABLES_DIR: Final = "timetables/"
_TIMETABLES_SECTION: Final = "timetables"
#: Fecha fija de las entradas ZIP: la fecha real va en el manifiesto.
_ZIP_EPOCH: Final = (1980, 1, 1, 0, 0, 0)

#: Una migración eleva `(manifest, entradas)` de una versión a la siguiente.
#: Las entradas son los JSON ya parseados, por nombre de archivo.
Migration = Callable[[JsonObject, dict[str, JsonValue]], tuple[JsonObject, dict[str, JsonValue]]]

#: Registro de migraciones `(desde, hasta) -> transformación`. Vacío en 1.0.0.
_MIGRATIONS: dict[tuple[str, str], Migration] = {}


class RspError(Exception):
    """Error del archivo `.rsp`: formato, E/S o contenido inválido."""


class RspChecksumError(RspError):
    """Una entrada no coincide con su checksum: archivo manipulado o corrupto."""


class RspVersionError(RspError):
    """El archivo tiene una versión de formato no soportada ni migrable."""


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _canonical_bytes(doc: JsonValue) -> bytes:
    """JSON determinista: base de los checksums y de diffs limpios."""
    try:
        texto = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    except ValueError as exc:  # NaN/inf: no son JSON estándar
        raise RspError(f"valor no representable en JSON: {exc}") from exc
    return (texto + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _app_version() -> str:
    try:
        return metadata.version("scheduling-platform")
    except metadata.PackageNotFoundError:  # pragma: no cover - sin instalar
        return "0.0.0"


def _parse_version(version: str) -> tuple[int, int, int]:
    partes = version.split(".")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        raise RspVersionError(f"format_version inválida: {version!r} (se esperaba X.Y.Z)")
    return int(partes[0]), int(partes[1]), int(partes[2])


_SLUG_RE: Final = re.compile(r"[^A-Za-z0-9_-]+")


def _timetable_entry(timetable_id: str, used: set[str]) -> str:
    """Nombre de archivo estable para un horario: slug legible + hash del id.

    `UntisProject` rechaza ids de horario repetidos, así que dos horarios solo
    compartirían nombre si dos ids distintos dieran el mismo slug y los mismos
    8 primeros caracteres del hash; en ese caso se usa el hash completo.
    """
    slug = _SLUG_RE.sub("_", timetable_id).strip("_")[:40] or "horario"
    digest = _sha256(timetable_id.encode("utf-8"))
    nombre = f"{_TIMETABLES_DIR}{slug}-{digest[:8]}.json"
    if nombre in used:
        nombre = f"{_TIMETABLES_DIR}{slug}-{digest}.json"
    used.add(nombre)
    return nombre


# --------------------------------------------------------------------------- #
# Migraciones
# --------------------------------------------------------------------------- #


def register_migration(from_version: str, to_version: str, transform: Migration) -> None:
    """Registra la migración `from_version -> to_version` (elevación de esquema)."""
    _parse_version(from_version)
    _parse_version(to_version)
    _MIGRATIONS[(from_version, to_version)] = transform


def migrate(
    manifest: JsonObject, entries: dict[str, JsonValue]
) -> tuple[JsonObject, dict[str, JsonValue]]:
    """Eleva `(manifest, entries)` hasta la versión actual aplicando migraciones en cadena.

    - Versión mayor más nueva que la soportada: `RspVersionError` (no se sabe leer).
    - Misma versión mayor pero menor/parche más nuevos: se acepta tal cual; la
      decodificación tolerante ignora lo que no conoce.
    - Versión anterior: se aplican migraciones mientras haya una registrada desde
      la versión en curso; si se acaba la cadena sin llegar a la versión mayor
      actual, `RspVersionError`.
    """
    actual = _parse_version(FORMAT_VERSION)
    raw = manifest.get("format_version")
    if not isinstance(raw, str):
        raise RspVersionError("el manifiesto no declara format_version")
    version = raw
    if _parse_version(version)[0] > actual[0]:
        raise RspVersionError(
            f"el archivo usa el formato {version}, más nuevo que el soportado "
            f"({FORMAT_VERSION}); actualiza RealSchool para abrirlo"
        )
    vistos: set[str] = set()
    while version != FORMAT_VERSION:
        destino = next((hasta for (desde, hasta) in _MIGRATIONS if desde == version), None)
        if destino is None:
            break
        if version in vistos:  # pragma: no cover - registro mal formado
            raise RspVersionError(f"ciclo de migración en la versión {version!r}")
        vistos.add(version)
        manifest, entries = _MIGRATIONS[(version, destino)](manifest, entries)
        manifest = {**manifest, "format_version": destino}
        version = destino
    if _parse_version(version)[0] != actual[0]:
        raise RspVersionError(
            f"formato .rsp {version} no soportado: no hay ruta de migración hasta {FORMAT_VERSION}"
        )
    return manifest, entries


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #


def _entries_of(project: UntisProject) -> tuple[dict[str, JsonValue], list[JsonValue]]:
    """Parte el proyecto en entradas por archivo. Devuelve (entradas, orden de horarios)."""
    doc = project_to_dict(project)
    entries: dict[str, JsonValue] = {}
    for section in PROJECT_SECTIONS:
        if section != _TIMETABLES_SECTION:
            entries[f"{section}.json"] = doc[section]
    orden: list[JsonValue] = []
    usados: set[str] = set()
    horarios = doc[_TIMETABLES_SECTION]
    assert isinstance(horarios, list)
    for tt, horario in zip(project.timetables, horarios, strict=True):
        nombre = _timetable_entry(tt.id, usados)
        entries[nombre] = horario
        orden.append(nombre)
    return entries, orden


def _existing_created(target: Path) -> str | None:
    """Sello `created` de un `.rsp` que ya exista en `target` (se conserva al guardar)."""
    if not target.is_file():
        return None
    try:
        with zipfile.ZipFile(target) as archive:
            creado = json.loads(archive.read(MANIFEST)).get("created")
    except OSError, KeyError, ValueError, zipfile.BadZipFile, AttributeError:
        return None
    return creado if isinstance(creado, str) else None


def _atomic_write(target: Path, data: bytes) -> None:
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise RspError(f"no se pudo escribir {target}: {exc}") from exc


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for nombre in [MANIFEST, *sorted(n for n in files if n != MANIFEST)]:
            info = zipfile.ZipInfo(nombre, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[nombre])
    return buffer.getvalue()


def save_rsp(
    project: UntisProject,
    path: str | Path,
    *,
    now: datetime | None = None,
    created: datetime | None = None,
) -> None:
    """Guarda el proyecto como `.rsp` de forma atómica y determinista.

    `now` fija el sello `modified` (por defecto, la hora actual en UTC). `created`
    fija el sello de creación; si se omite se conserva el del `.rsp` que ya exista
    en `path`, o se usa `now` si es un archivo nuevo. Toda la serialización ocurre
    en memoria **antes** de tocar el disco.
    """
    target = Path(path)
    momento = _iso(now or datetime.now(UTC))
    creado = _iso(created) if created is not None else _existing_created(target) or momento
    entries, orden = _entries_of(project)
    serializadas = {nombre: _canonical_bytes(doc) for nombre, doc in entries.items()}
    manifest: JsonObject = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app_version": _app_version(),
        "created": creado,
        "modified": momento,
        "timetables": orden,
        "checksums": {nombre: _sha256(data) for nombre, data in serializadas.items()},
    }
    _atomic_write(target, _zip_bytes({**serializadas, MANIFEST: _canonical_bytes(manifest)}))


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #


def _loads(data: bytes, nombre: str) -> JsonValue:
    try:
        valor: JsonValue = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RspError(f"JSON inválido en {nombre!r}: {exc}") from exc
    return valor


def read_rsp_entries(path: str | Path) -> tuple[JsonObject, dict[str, JsonValue]]:
    """Lee un `.rsp`, verifica firma, integridad y versión, y aplica migraciones.

    Devuelve `(manifest, entradas)` ya elevados a `FORMAT_VERSION`, con las
    entradas JSON parseadas por nombre de archivo. Útil para herramientas que
    inspeccionan el archivo sin reconstruir el modelo.
    """
    target = Path(path)
    if not target.is_file():
        raise RspError(f"no existe el archivo .rsp: {target}")
    try:
        with zipfile.ZipFile(io.BytesIO(target.read_bytes())) as archive:
            nombres = set(archive.namelist())
            if MANIFEST not in nombres:
                raise RspError(f"{target} no es un .rsp válido (falta {MANIFEST})")
            crudo = {n: archive.read(n) for n in sorted(nombres) if not n.endswith("/")}
    except zipfile.BadZipFile as exc:
        raise RspError(f"{target} no es un archivo .rsp válido: {exc}") from exc
    except OSError as exc:
        raise RspError(f"no se pudo leer {target}: {exc}") from exc

    manifest_raw = _loads(crudo.pop(MANIFEST), MANIFEST)
    if not isinstance(manifest_raw, dict):
        raise RspError(f"{MANIFEST} debe ser un objeto JSON")
    manifest: JsonObject = manifest_raw
    if manifest.get("format") != FORMAT_NAME:
        raise RspError(f"{target} no es un proyecto RealSchool (format={manifest.get('format')!r})")
    # Versión antes que integridad: un archivo de una versión mayor futura podría
    # usar otro esquema de checksums y el error correcto es "actualiza la app".
    version = manifest.get("format_version")
    if not isinstance(version, str):
        raise RspVersionError("el manifiesto no declara format_version")
    if _parse_version(version)[0] > _parse_version(FORMAT_VERSION)[0]:
        migrate(manifest, {})  # lanza RspVersionError con el mensaje completo

    checksums = manifest.get("checksums")
    if not isinstance(checksums, dict):
        raise RspChecksumError(f"{MANIFEST} sin mapa de checksums")
    for nombre, esperado in checksums.items():
        if nombre not in crudo:
            raise RspChecksumError(f"falta la entrada {nombre!r} declarada en el manifiesto")
        if not isinstance(esperado, str) or _sha256(crudo[nombre]) != esperado:
            raise RspChecksumError(
                f"checksum no coincide para {nombre!r} (archivo manipulado o corrupto)"
            )
    # Una entrada conocida sin checksum es sospechosa (alguien la añadió a mano).
    conocidas = {f"{s}.json" for s in PROJECT_SECTIONS}
    for nombre in crudo:
        if nombre not in checksums and (nombre in conocidas or nombre.startswith(_TIMETABLES_DIR)):
            raise RspChecksumError(f"la entrada {nombre!r} no figura en los checksums")
    # Entradas desconocidas y no declaradas: se ignoran (compatibilidad hacia
    # delante con archivos que traen datos extra), pero nunca se confía en ellas.
    entries = {n: _loads(data, n) for n, data in crudo.items() if n in checksums}
    return migrate(manifest, entries)


def _timetable_order(manifest: JsonObject, entries: dict[str, JsonValue]) -> list[str]:
    declarados = manifest.get("timetables")
    if isinstance(declarados, list):
        orden = [n for n in declarados if isinstance(n, str)]
    else:
        orden = sorted(n for n in entries if n.startswith(_TIMETABLES_DIR))
    for nombre in orden:
        if nombre not in entries:
            raise RspError(f"el manifiesto lista el horario {nombre!r} pero no está en el archivo")
    return orden


def load_rsp(path: str | Path) -> UntisProject:
    """Abre un `.rsp` y reconstruye el `UntisProject` (verificado y migrado)."""
    manifest, entries = read_rsp_entries(path)
    doc: JsonObject = {}
    for section in PROJECT_SECTIONS:
        nombre = f"{section}.json"
        if section != _TIMETABLES_SECTION and nombre in entries:
            doc[section] = entries[nombre]
    doc[_TIMETABLES_SECTION] = [entries[n] for n in _timetable_order(manifest, entries)]
    try:
        return project_from_dict(doc)
    except (ValueError, TypeError) as exc:
        raise RspError(f"contenido inválido en {path}: {exc}") from exc
