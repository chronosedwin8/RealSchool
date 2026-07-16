"""Capa de Aplicación: casos de uso, dispatcher y contrato de proceso (Fase 2).

Se sitúa entre la CLI y la API pública del ``SchedulingEngine``. Encapsula cada
operación como un :class:`Command` (patrón Command + inyección de dependencias) y
garantiza el contrato de streams/exit-codes. **Regla de oro:** el Core de
optimización (``core``/``academic``/``sal``/``plugins``/``pipeline``/``engine``)
nunca importa esta capa (verificado por ``tests/test_architecture.py``).
"""

from __future__ import annotations

from .commands.base import Command, CommandResult
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

__all__ = [
    "AppContext",
    "AppError",
    "AppLogger",
    "Command",
    "CommandDispatcher",
    "CommandResult",
    "ConfigError",
    "InfeasibleError",
    "InternalError",
    "ScheduleProject",
    "SolveTimeoutError",
    "new_project",
    "open_project",
    "save_project",
]
