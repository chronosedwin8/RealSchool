"""Contexto de ejecución que el dispatcher inyecta en cada comando.

Un comando **nunca** escribe directamente en ``stdout``: lee sus dependencias del
:class:`AppContext` (solver, logger a stderr, formato de salida) y devuelve un
``CommandResult`` con el dato estructurado; es el dispatcher quien lo emite por
``stdout``. Así la disciplina de streams queda garantizada por construcción.

Excepción explícita: con ``--json-stream`` (para una GUI), los eventos de
progreso SÍ van por ``stdout`` como JSONL (son el canal de datos en vivo). Fuera
de ese modo, el progreso se registra en ``stderr`` como texto humano.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TextIO

from ..engine import SolverFactory
from ..pipeline.events import ProgressEvent
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

    def emit_progress(self, event: ProgressEvent) -> None:
        """Publica un evento de progreso: JSONL a stdout si stream, si no a stderr."""
        if self.json_stream:
            self.out.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            self.out.flush()
        else:
            self.logger.info(f"[{event.percentage:3d}%] {event.event} ({event.stage})")
