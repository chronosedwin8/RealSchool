"""Logger de la Capa de Aplicación: escribe SIEMPRE a ``stderr``.

El contrato de streams reserva ``stdout`` para la salida estructurada de datos;
los logs, avisos y progreso van a ``stderr``. Este logger nunca toca ``stdout``,
garantizando por construcción que ``comando > out.json`` no filtre trazas al
archivo (invariante Zero-Leakage). El log en tiempo real por ``stdout``
(``--json-stream``, para la GUI) se añade en H12 como canal aparte y explícito.
"""

from __future__ import annotations

from typing import TextIO


class AppLogger:
    """Escribe mensajes humanos a ``stderr`` (nunca a ``stdout``)."""

    def __init__(self, err: TextIO, *, quiet: bool = False) -> None:
        self._err = err
        self._quiet = quiet

    def info(self, message: str) -> None:
        if not self._quiet:
            self._err.write(message + "\n")

    def warning(self, message: str) -> None:
        self._err.write(f"AVISO: {message}\n")

    def error(self, message: str) -> None:
        self._err.write(f"ERROR: {message}\n")
