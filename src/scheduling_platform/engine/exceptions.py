"""Errores de la capa del motor."""

from __future__ import annotations


class EngineError(Exception):
    """Raíz de los errores del motor."""


class SolutionExtractionError(EngineError):
    """La solución del solver no pudo reconstruirse (modelo mal formado)."""
