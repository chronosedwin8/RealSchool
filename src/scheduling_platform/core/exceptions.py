"""Jerarquía de errores del dominio canónico.

Todos los errores del núcleo derivan de :class:`DomainError`, de modo que las
capas superiores puedan capturar cualquier violación de invariante del modelo
con un único tipo raíz.
"""

from __future__ import annotations


class DomainError(Exception):
    """Raíz de todos los errores del modelo canónico."""


class InvalidTimeGrid(DomainError):
    """La rejilla temporal o alguno de sus segmentos es inconsistente."""


class InvalidEntity(DomainError):
    """Una entidad (Resource, Task, ...) viola una invariante propia."""


class InvalidAssignment(DomainError):
    """Una asignación es imposible respecto de la tarea o la rejilla."""


class ReferentialIntegrityError(DomainError):
    """Un agregado referencia entidades inexistentes o duplicadas."""


def require(condition: bool, exc: type[DomainError], message: str) -> None:
    """Valida una invariante; lanza ``exc(message)`` si no se cumple.

    Centraliza el patrón de validación para mantener los ``__post_init__``
    legibles y uniformes en todo el núcleo.
    """
    if not condition:
        raise exc(message)
