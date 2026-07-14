"""Identidades tipadas del dominio académico.

Enteros envueltos en :class:`typing.NewType` para impedir mezclas accidentales
(p. ej. un ``TeacherId`` donde se espera un ``GroupId``), verificado por
``mypy --strict``. El adaptador (``adapter.py``) traduce estos IDs a los IDs
del Modelo Canónico.
"""

from __future__ import annotations

from typing import NewType

TeacherId = NewType("TeacherId", int)
RoomId = NewType("RoomId", int)
GroupId = NewType("GroupId", int)
SubjectId = NewType("SubjectId", int)
AssignmentId = NewType("AssignmentId", int)
