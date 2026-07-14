"""Errores del CIR y de sus pases de optimización."""

from __future__ import annotations


class CirError(Exception):
    """Raíz de los errores del CIR."""


class StructuralContradictionError(CirError):
    """El modelo es estructuralmente infactible (detectado antes del solver).

    Lleva la lista de razones legibles; el Conflict Explanation Engine (Fase 5)
    las presentará al usuario.
    """

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))
