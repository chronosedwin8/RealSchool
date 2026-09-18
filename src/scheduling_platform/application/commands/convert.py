"""Caso de uso ``convert``: pasar un proyecto entre formatos.

Orígenes: Untis XmlInterface (`.xml`), proyecto RealSchool (`.rsp`), proyecto
antiguo (`.bjs`) o una carpeta con archivos GPU de Untis.
Destinos: `.rsp` (formato nativo), `.xml` (XmlInterface), una carpeta (archivos
GPU001-007 y GPU016, listos para Untis y MiUntisWeb) o, por compatibilidad, el
antiguo `.bjs` desde un `.xml`.

Todo pasa por la Fachada Untis: un modelo, varios serializadores (sección 9 del
documento maestro).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import ClassVar

from ...untis import UntisToCanonicalAdapter, parse_untis
from ..context import AppContext
from ..errors import ConfigError
from ..project import new_project
from ..untis import UntisService
from .base import Command, CommandResult

#: Orígenes aceptados (además de una carpeta con archivos GPU).
SOURCE_SUFFIXES = (".xml", ".rsp", ".bjs")
#: Destinos aceptados (además de una carpeta para GPU).
DEST_SUFFIXES = (".rsp", ".xml", ".bjs")


class ConvertCommand(Command):
    """Convierte entre XmlInterface, GPU, `.rsp` y el `.bjs` antiguo."""

    name: ClassVar[str] = "convert"

    def __init__(self, source: str, dest: str, *, name: str | None = None) -> None:
        self._source = source
        self._dest = dest
        self._name = name

    def execute(self, ctx: AppContext) -> CommandResult:
        source = Path(self._source)
        dest = Path(self._dest)
        if not source.exists():
            raise ConfigError(f"no existe el archivo de origen: {source}")
        if not source.is_dir() and source.suffix.lower() not in SOURCE_SUFFIXES:
            raise ConfigError(
                f"formato de origen no soportado: {source.suffix!r} "
                "(usa .xml de Untis, .rsp, .bjs o una carpeta GPU)"
            )
        destino_gpu = dest.suffix == "" or dest.is_dir()
        if not destino_gpu and dest.suffix.lower() not in DEST_SUFFIXES:
            raise ConfigError(
                f"formato de destino no soportado: {dest.suffix!r} "
                "(usa .rsp, .xml o una carpeta para GPU)"
            )
        if dest.suffix.lower() == ".bjs":
            return self._legacy_bjs(source, dest)

        svc = UntisService()
        try:
            sesion = svc.open(source)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"no se pudo leer {source.name}: {exc}") from exc
        if self._name:
            sesion.project = replace(
                sesion.project, school=replace(sesion.project.school, name=self._name)
            )

        if destino_gpu:
            escritos = [str(p) for p in svc.export_gpu(sesion, dest)]
            creado = str(dest)
        elif dest.suffix.lower() == ".xml":
            creado = str(svc.export_xml(sesion, dest))
            escritos = [creado]
        else:
            creado = str(svc.save(sesion, dest))
            escritos = [creado]

        p = sesion.project
        payload = {
            "created": creado,
            "files": escritos,
            "name": p.school.name or source.stem,
            "classes": len(p.classes),
            "teachers": len(p.teachers),
            "rooms": len(p.rooms),
            "subjects": len(p.subjects),
            "lessons": len(p.lessons),
            "timetables": len(p.timetables),
        }
        return CommandResult(payload=payload, messages=(f"convertido {source.name} -> {dest}",))

    def _legacy_bjs(self, source: Path, dest: Path) -> CommandResult:
        """Ruta antigua Untis XML -> `.bjs` (se conserva por compatibilidad)."""
        if source.suffix.lower() != ".xml":
            raise ConfigError("el destino .bjs solo admite un .xml de Untis como origen")
        translation = UntisToCanonicalAdapter().translate(parse_untis(source))
        problem = translation.problem
        name = self._name or source.stem
        new_project(dest, name, problem)
        payload = {
            "created": str(dest),
            "name": name,
            "classes": len(problem.tasks),
            "resources": len(problem.resources),
        }
        return CommandResult(payload=payload, messages=(f"convertido {source.name} -> {dest}",))
