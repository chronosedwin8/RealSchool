"""Comando ``config validate``: análisis semántico de la configuración.

Carga ``engine.yaml`` y/o ``plugins.yaml`` y valida su consistencia contra el
catálogo de restricciones antes de cualquier ejecución. Un error de configuración
se propaga como ``ConfigError`` (exit 1); el éxito devuelve un resumen legible.
"""

from __future__ import annotations

from typing import ClassVar

from ..config import load_engine_config_file, load_plugins_config_file
from ..context import AppContext
from ..errors import ConfigError
from .base import Command, CommandResult


class ConfigValidateCommand(Command):
    """Valida los archivos de configuración del motor."""

    name: ClassVar[str] = "config-validate"

    def __init__(self, engine_path: str | None = None, plugins_path: str | None = None) -> None:
        self._engine_path = engine_path
        self._plugins_path = plugins_path

    def execute(self, ctx: AppContext) -> CommandResult:
        if self._engine_path is None and self._plugins_path is None:
            raise ConfigError("indica al menos engine.yaml o plugins.yaml para validar")

        payload: dict[str, object] = {"valid": True}
        messages: list[str] = []

        if self._engine_path is not None:
            engine = load_engine_config_file(self._engine_path)
            payload["engine"] = {
                "default_solver": engine.default_solver,
                "threads": engine.threads,
                "max_time_seconds": engine.max_time_seconds,
                "random_seed": engine.random_seed,
            }
            messages.append(
                f"engine.yaml OK (solver {engine.default_solver}, {engine.threads} hilos)"
            )

        if self._plugins_path is not None:
            plugins = load_plugins_config_file(self._plugins_path)
            enabled = sum(1 for p in plugins.plugins if p.enabled)
            payload["plugins"] = {"total": len(plugins.plugins), "enabled": enabled}
            plugins.build_registry()  # construye el registro: valida que todo encaje
            messages.append(f"plugins.yaml OK ({enabled}/{len(plugins.plugins)} activos)")

        return CommandResult(exit_code=0, payload=payload, messages=tuple(messages))
