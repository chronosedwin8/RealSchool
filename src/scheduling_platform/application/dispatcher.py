"""Command Dispatcher: composición, inyección de dependencias y contrato de streams.

Es el único punto que:
1. construye el :class:`AppContext` (inyecta el solver factory, el logger a
   stderr, el formato de salida);
2. ejecuta el comando y traduce **cualquier** fallo a un código de salida estable
   (0/1/2/3/4), sin que ninguna excepción escape del proceso sin código;
3. emite el ``payload`` estructurado por ``stdout`` y los mensajes por ``stderr``.

Como los comandos nunca escriben en ``stdout`` (solo devuelven ``payload``), la
disciplina de streams queda garantizada por construcción (invariante Zero-Leakage).
"""

from __future__ import annotations

import json
from typing import Any, TextIO

import yaml

from ..engine import SolverFactory
from ..sal.ortools_solver import ORToolsSolver
from .commands.base import Command
from .context import AppContext
from .errors import AppError, ConfigError, InternalError
from .log import AppLogger

_FORMATS = ("json", "yaml", "markdown")
_EXIT_INTERRUPTED = 130  # convención POSIX para terminación por SIGINT (128 + 2)


def _serialize(payload: Any, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(payload, indent=2, ensure_ascii=False)
    if output_format == "yaml":
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip("\n")
    # markdown: el comando ya produjo texto listo para imprimir
    if isinstance(payload, str):
        return payload
    raise ConfigError("el formato 'markdown' requiere que el comando produzca texto")


class CommandDispatcher:
    """Ejecuta comandos aislando la lógica del contrato de proceso (streams/exit)."""

    def __init__(self, solver_factory: SolverFactory = ORToolsSolver) -> None:
        self._solver_factory = solver_factory

    def dispatch(
        self,
        command: Command,
        *,
        out: TextIO,
        err: TextIO,
        output_format: str = "json",
        json_stream: bool = False,
        quiet: bool = False,
    ) -> int:
        """Ejecuta ``command`` y devuelve el código de salida del proceso."""
        logger = AppLogger(err, quiet=quiet)
        if output_format not in _FORMATS:
            logger.error(f"formato de salida no soportado: {output_format}")
            return ConfigError.exit_code

        ctx = AppContext(
            out=out,
            err=err,
            logger=logger,
            solver_factory=self._solver_factory,
            output_format=output_format,
            json_stream=json_stream,
        )
        try:
            result = command.execute(ctx)
            payload_text = (
                None if result.payload is None else _serialize(result.payload, output_format)
            )
        except KeyboardInterrupt:
            # Ctrl+C / SIGTERM: salida segura. La escritura de proyecto es atómica
            # (H2), así que el .schedule original nunca queda corrupto.
            logger.error("ejecución interrumpida por el usuario")
            return _EXIT_INTERRUPTED
        except AppError as exc:
            logger.error(str(exc) or exc.__class__.__name__)
            return exc.exit_code
        except Exception as exc:  # frontera del proceso: cualquier error -> exit 4
            logger.error(f"error interno: {exc}")
            return InternalError.exit_code

        if result.payload is not None:
            if json_stream:
                final = {"event": "completed", "result": result.payload}
                out.write(json.dumps(final, ensure_ascii=False) + "\n")
            elif payload_text is not None:
                out.write(payload_text + "\n")
        for message in result.messages:
            logger.info(message)
        return result.exit_code
