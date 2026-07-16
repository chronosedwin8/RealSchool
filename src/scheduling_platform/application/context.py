"""Contexto de ejecución que el dispatcher inyecta en cada comando.

Un comando **nunca** escribe directamente en ``stdout``: lee sus dependencias del
:class:`AppContext` (solver, logger a stderr, formato de salida) y devuelve un
``CommandResult`` con el dato estructurado; es el dispatcher quien lo emite por
``stdout``. Así la disciplina de streams queda garantizada por construcción.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TextIO

from ..engine import SolverFactory
from .log import AppLogger


@dataclass(frozen=True, slots=True)
class AppContext:
    """Dependencias inyectadas a un comando en tiempo de ejecución."""

    out: TextIO
    err: TextIO
    logger: AppLogger
    solver_factory: SolverFactory
    output_format: str = "json"
    json_stream: bool = False
