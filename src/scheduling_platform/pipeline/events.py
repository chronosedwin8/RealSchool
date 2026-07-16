"""Eventos de progreso del pipeline (para clientes en vivo: GUI, CI).

Un :class:`ProgressEvent` describe un hito de la ejecución (etapa + porcentaje +
detalle). El pipeline los emite a través de un callback **opcional** (``on_event``,
``None`` por defecto): sin callback, el comportamiento es idéntico al histórico.
La Capa de Aplicación los serializa como JSONL a ``stdout`` con ``--json-stream``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Hito de la ejecución del pipeline."""

    event: str
    stage: str
    percentage: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "stage": self.stage,
            "percentage": self.percentage,
            **self.detail,
        }


ProgressCallback = Callable[[ProgressEvent], None]


def emit(
    on_event: ProgressCallback | None, event: str, stage: str, percentage: int, **detail: Any
) -> None:
    """Invoca el callback si existe (no-op cuando ``on_event`` es ``None``)."""
    if on_event is not None:
        on_event(ProgressEvent(event=event, stage=stage, percentage=percentage, detail=detail))
