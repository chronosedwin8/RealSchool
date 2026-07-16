"""Errores de la Capa de Aplicación, mapeados a códigos de salida del proceso.

El contrato de la CLI (Fase 2) fija los exit codes: ``0`` éxito, ``1`` config o
parámetros, ``2`` modelo inviable, ``3`` timeout sin solución, ``4`` error interno.
Cada excepción de aplicación lleva su código, de modo que el ``CommandDispatcher``
traduce cualquier fallo a un código estable sin ramas ad-hoc.
"""

from __future__ import annotations


class AppError(Exception):
    """Base de los errores de aplicación. Por defecto, error interno (4)."""

    exit_code: int = 4


class ConfigError(AppError):
    """Sintaxis, parámetros o configuración inválidos (exit 1)."""

    exit_code = 1


class InfeasibleError(AppError):
    """El modelo no tiene solución; se acompaña de la explicación (exit 2)."""

    exit_code = 2


class SolveTimeoutError(AppError):
    """Se agotó el tiempo sin encontrar una solución factible (exit 3)."""

    exit_code = 3


class InternalError(AppError):
    """Fallo interno: E/S, corrupción o bug de asignación (exit 4)."""

    exit_code = 4
