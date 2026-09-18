"""Registro de fallos: lo que la aplicación deja escrito si se cierra de golpe.

Un fallo nativo (segmentation fault dentro de Qt) no produce traza de Python:
el proceso muere sin más. `faulthandler` escribe en ese momento la pila de
todos los hilos en un archivo, y un `sys.excepthook` guarda también las
excepciones de Python que se escapen en un slot de Qt (que Qt solo imprime en
una consola que el usuario no ve). Así, tras un cierre inesperado, el usuario
puede enviar `crash.log` y se ve exactamente dónde ocurrió.
"""

from __future__ import annotations

import datetime
import faulthandler
import os
import sys
import traceback
from pathlib import Path
from types import TracebackType
from typing import TextIO

_log: TextIO | None = None


def log_dir() -> Path:
    """Carpeta de registros: `%LOCALAPPDATA%\\RealSchool` (o `~/.realschool`)."""
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "RealSchool" if base else Path.home() / ".realschool"


def log_path() -> Path:
    return log_dir() / "crash.log"


def install() -> Path | None:
    """Activa el registro de fallos. Devuelve la ruta del archivo, o `None` si no se pudo."""
    global _log
    if _log is not None:
        return log_path()
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        _log = open(log_path(), "a", encoding="utf-8")  # noqa: SIM115 - abierto toda la sesión
    except OSError:
        return None
    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    _log.write(f"\n=== RealSchool iniciado {ahora} (pid {os.getpid()}) ===\n")
    _log.flush()
    faulthandler.enable(file=_log, all_threads=True)
    anterior = sys.excepthook

    def gancho(tipo: type[BaseException], valor: BaseException, tb: TracebackType | None) -> None:
        if _log is not None:
            _log.write(f"--- Excepción no controlada {datetime.datetime.now():%H:%M:%S} ---\n")
            _log.write("".join(traceback.format_exception(tipo, valor, tb)))
            _log.flush()
        anterior(tipo, valor, tb)

    sys.excepthook = gancho
    return log_path()


def note(message: str) -> None:
    """Deja una línea de contexto (p. ej. qué ventana se abrió) en el registro."""
    if _log is not None:
        _log.write(f"{datetime.datetime.now():%H:%M:%S} {message}\n")
        _log.flush()


def close_cleanly() -> None:
    """Marca un cierre normal: si falta esta línea, el cierre fue inesperado."""
    if _log is not None:
        _log.write(f"=== cierre normal {datetime.datetime.now():%H:%M:%S} ===\n")
        _log.flush()
