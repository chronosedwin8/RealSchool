"""Capa de Aplicación: casos de uso, dispatcher y contrato de proceso (Fase 2).

Se sitúa entre la CLI y la API pública del ``SchedulingEngine``. Encapsula cada
operación como un :class:`Command` (patrón Command + inyección de dependencias) y
garantiza el contrato de streams/exit-codes. **Regla de oro:** el Core de
optimización (``core``/``academic``/``sal``/``plugins``/``pipeline``/``engine``)
nunca importa esta capa (verificado por ``tests/test_architecture.py``).
"""

from __future__ import annotations

from .commands.base import Command, CommandResult
from .commands.config_validate import ConfigValidateCommand
from .commands.convert import ConvertCommand
from .commands.inspect_project import ExplainCommand, ValidateCommand
from .commands.solve import GenerateCommand, OptimizeCommand
from .config import (
    EngineConfig,
    PluginsConfig,
    PluginSetting,
    load_engine_config,
    load_plugins_config,
)
from .context import AppContext
from .dispatcher import CommandDispatcher
from .errors import (
    AppError,
    ConfigError,
    InfeasibleError,
    InternalError,
    SolveTimeoutError,
)
from .log import AppLogger
from .project import ScheduleProject, new_project, open_project, save_project
from .solvers import SOLVER_NAMES, solver_factory_for

__all__ = [
    "SOLVER_NAMES",
    "AppContext",
    "AppError",
    "AppLogger",
    "Command",
    "CommandDispatcher",
    "CommandResult",
    "ConfigError",
    "ConfigValidateCommand",
    "ConvertCommand",
    "EngineConfig",
    "ExplainCommand",
    "GenerateCommand",
    "InfeasibleError",
    "InternalError",
    "OptimizeCommand",
    "PluginSetting",
    "PluginsConfig",
    "ScheduleProject",
    "SolveTimeoutError",
    "ValidateCommand",
    "load_engine_config",
    "load_plugins_config",
    "new_project",
    "open_project",
    "save_project",
    "solver_factory_for",
]
