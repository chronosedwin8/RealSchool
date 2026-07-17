"""Señal de cancelación cooperativa para operaciones largas (Fase 5).

La GUI corre el solver en un hilo aparte; el botón *Detener* activa un
:class:`CancelToken` que el motor consulta a través del seam opt-in
``SolverConfig.should_stop``. Es una simple bandera *thread-safe*: sin acoplar la
capa de aplicación a ningún toolkit ni al solver concreto.
"""

from __future__ import annotations

import threading


class CancelToken:
    """Bandera de cancelación consultable desde otro hilo."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Solicita la cancelación (idempotente)."""
        self._event.set()

    def is_cancelled(self) -> bool:
        """``True`` si ya se solicitó cancelar. Apto como ``should_stop``."""
        return self._event.is_set()

    def reset(self) -> None:
        """Rearma el token para una nueva operación."""
        self._event.clear()
