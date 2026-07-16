"""Capa de entrada CLI (Typer): ``schedule-engine``.

Delgada por diseño: traduce argumentos de consola a comandos de la Capa de
Aplicación y respeta el contrato de streams/exit-codes. No importa el Core
directamente ni contiene lógica de negocio.
"""

from __future__ import annotations

from .main import app

__all__ = ["app"]
