"""Identidades tipadas del modelo canónico.

Cada entidad se identifica con un entero envuelto en un :class:`typing.NewType`
distinto. Los enteros permiten indexar variables y matrices del solver sin
diccionarios de traducción intermedios (ADR-002/D3), y los tipos distintos
impiden mezclar accidentalmente, por ejemplo, un ``ResourceId`` con un
``TaskId`` (verificado por ``mypy --strict``).

La asignación concreta de los enteros es responsabilidad del adaptador de
dominio (Fase 2); el núcleo únicamente los transporta.
"""

from __future__ import annotations

from typing import NewType

ResourceId = NewType("ResourceId", int)
TaskId = NewType("TaskId", int)
ConstraintId = NewType("ConstraintId", int)
TimeSlotIndex = NewType("TimeSlotIndex", int)
