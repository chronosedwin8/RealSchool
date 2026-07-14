"""Errores del dominio académico.

Derivan de :class:`~scheduling_platform.core.exceptions.DomainError` para que
las capas superiores capturen cualquier error del sistema con un único tipo
raíz, y reutilizan el helper ``require`` del núcleo.
"""

from __future__ import annotations

from ..core.exceptions import DomainError


class AcademicError(DomainError):
    """Raíz de los errores del dominio académico."""


class InvalidTimeFrame(AcademicError):
    """El marco horario (días/períodos) es inconsistente."""


class InvalidAcademicEntity(AcademicError):
    """Una entidad académica viola una invariante propia."""


class AcademicIntegrityError(AcademicError):
    """Un agregado académico referencia entidades inexistentes o duplicadas."""
