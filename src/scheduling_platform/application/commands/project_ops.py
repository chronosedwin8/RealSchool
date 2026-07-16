"""Operaciones de contenedor ``.bjs`` (Fase 3, B4): info, validate, extract, pack.

Integradas en el binario único ``schedule-engine`` bajo el subcomando ``project``,
siguiendo el patrón Command de la Fase 2. Son operaciones de bajo nivel del
contenedor, distintas del ``validate`` de factibilidad (que analiza el problema):
aquí se valida el **contrato de datos** (estructura, integridad, referencias).
"""

from __future__ import annotations

from typing import ClassVar

from ..bjs_validation import check_consistency
from ..context import AppContext
from ..errors import ConfigError
from ..project import extract_project, open_project, pack_project
from .base import Command, CommandResult


class ProjectInfoCommand(Command):
    """Resumen de metadatos del contenedor y estado de la solución."""

    name: ClassVar[str] = "project-info"

    def __init__(self, path: str) -> None:
        self._path = path

    def execute(self, ctx: AppContext) -> CommandResult:
        project = open_project(self._path)
        manifest = project.manifest
        score = project.metrics.get("quality_score") if project.metrics else None
        payload = {
            "project_name": manifest.get("project_name"),
            "uuid": manifest.get("uuid"),
            "format_version": manifest.get("format_version"),
            "engine_signature": manifest.get("engine_signature"),
            "has_solution": project.solution is not None,
            "score": score,
            "history_runs": len(project.history),
        }
        estado = "optimizado" if project.solution is not None else "sin resolver"
        return CommandResult(payload=payload, messages=(f"{payload['project_name']} · {estado}",))


class ProjectValidateCommand(Command):
    """Valida el contrato de datos: estructura + integridad + referencias."""

    name: ClassVar[str] = "project-validate"

    def __init__(self, path: str, *, strict: bool = False) -> None:
        self._path = path
        self._strict = strict

    def execute(self, ctx: AppContext) -> CommandResult:
        project = open_project(self._path)  # estructura + checksums + referencial
        warnings = check_consistency(project)
        if self._strict and warnings:
            raise ConfigError("validación estricta: " + "; ".join(warnings))
        payload = {"valid": True, "warnings": list(warnings)}
        messages = ["esquemas y checksums conformes", "validación referencial: consistente"]
        messages += [f"[WARN] {w}" for w in warnings]
        return CommandResult(payload=payload, messages=tuple(messages))


class ProjectExtractCommand(Command):
    """Descomprime el ``.bjs`` a JSONs git-friendly (sort_keys, indent 2)."""

    name: ClassVar[str] = "project-extract"

    def __init__(self, path: str, out: str) -> None:
        self._path = path
        self._out = out

    def execute(self, ctx: AppContext) -> CommandResult:
        written = extract_project(self._path, self._out)
        payload = {"extracted": len(written), "out": self._out}
        return CommandResult(
            payload=payload, messages=(f"extraído a {self._out} ({len(written)} archivos)",)
        )


class ProjectPackCommand(Command):
    """Re-empaqueta un directorio a ``.bjs`` de forma atómica y valida el resultado."""

    name: ClassVar[str] = "project-pack"

    def __init__(self, src: str, out: str) -> None:
        self._src = src
        self._out = out

    def execute(self, ctx: AppContext) -> CommandResult:
        project = pack_project(self._src, self._out)
        payload = {"packed": self._out, "project_name": project.manifest.get("project_name")}
        return CommandResult(
            payload=payload, messages=(f"empaquetado atómicamente en {self._out}",)
        )
