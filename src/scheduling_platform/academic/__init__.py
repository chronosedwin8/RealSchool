"""Módulo Académico (Fase 2).

Dominio específico: Docente, Aula, Materia, Grupo, Marco Horario, Carga
Académica, y el ``AcademicToCanonicalAdapter`` que lo traduce al Modelo
Canónico (``core``) y reconstruye el horario desde una solución. Esta capa no
conoce ningún solver: prohibido importar ``ortools`` aquí (verificado por
``tests/test_architecture.py`` y ``tests/test_core_isolation.py``).

.. deprecated:: R0 (ADR-034)
   Sustituido por ``scheduling_platform.untis_model`` (dominio Untis) y
   ``scheduling_platform.bridge`` (traducción al canónico). Se conserva solo
   como dependencia interna de ``benchmarks``; no usar en código nuevo.
"""

from __future__ import annotations

import warnings

from .adapter import (
    AcademicSchedule,
    AcademicToCanonicalAdapter,
    AcademicTranslation,
    ResourceOrigin,
    ScheduledClass,
    SessionOrigin,
)
from .entities import Room, StudentGroup, Subject, Teacher, TeachingAssignment
from .exceptions import (
    AcademicError,
    AcademicIntegrityError,
    InvalidAcademicEntity,
    InvalidTimeFrame,
)
from .ids import AssignmentId, GroupId, RoomId, SubjectId, TeacherId
from .problem import AcademicProblem
from .time_frame import TimeFrame

warnings.warn(
    "scheduling_platform.academic está obsoleto (ADR-034): usa "
    "scheduling_platform.untis_model y scheduling_platform.bridge.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "AcademicError",
    "AcademicIntegrityError",
    "AcademicProblem",
    "AcademicSchedule",
    "AcademicToCanonicalAdapter",
    "AcademicTranslation",
    "AssignmentId",
    "GroupId",
    "InvalidAcademicEntity",
    "InvalidTimeFrame",
    "ResourceOrigin",
    "Room",
    "RoomId",
    "ScheduledClass",
    "SessionOrigin",
    "StudentGroup",
    "Subject",
    "SubjectId",
    "Teacher",
    "TeacherId",
    "TeachingAssignment",
    "TimeFrame",
]
