"""Errores de serialización."""

from __future__ import annotations


class SerializationError(Exception):
    """Raíz de los errores de serialización."""


class UnsupportedSchemaVersion(SerializationError):
    """El documento fue escrito por una versión incompatible del formato."""
