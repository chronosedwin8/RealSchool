"""Caso de uso ``convert``: importar un formato externo al contenedor .schedule.

Instancia el adaptador de dominio (Untis XML -> Modelo Canónico), valida su
consistencia inicial y empaqueta el resultado en un ``.schedule`` nuevo.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from ...untis import UntisToCanonicalAdapter, parse_untis
from ..context import AppContext
from ..errors import ConfigError
from ..project import new_project
from .base import Command, CommandResult


class ConvertCommand(Command):
    """Convierte un origen externo (hoy: Untis XML) en un proyecto .schedule."""

    name: ClassVar[str] = "convert"

    def __init__(self, source: str, dest: str, *, name: str | None = None) -> None:
        self._source = source
        self._dest = dest
        self._name = name

    def execute(self, ctx: AppContext) -> CommandResult:
        source = Path(self._source)
        if not source.exists():
            raise ConfigError(f"no existe el archivo de origen: {source}")
        if source.suffix.lower() != ".xml":
            raise ConfigError(
                f"formato de origen no soportado: {source.suffix!r} (usa un .xml de Untis)"
            )

        translation = UntisToCanonicalAdapter().translate(parse_untis(source))
        problem = translation.problem
        name = self._name or source.stem
        new_project(self._dest, name, problem)

        payload = {
            "created": self._dest,
            "name": name,
            "classes": len(problem.tasks),
            "resources": len(problem.resources),
        }
        return CommandResult(
            payload=payload, messages=(f"convertido {source.name} -> {self._dest}",)
        )
