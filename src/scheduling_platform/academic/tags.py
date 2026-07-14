"""Esquema de tags para el emparejamiento recurso-requerimiento.

Centraliza cómo el adaptador nombra los tags que conectan un ``Task`` canónico
con los ``Resource`` que puede usar:

- Docente y grupo se **fijan** con un tag único (``teacher#42``, ``group#7``):
  solo el recurso correspondiente lo porta, de modo que el solver no tiene
  elección.
- El aula se **elige**: el requerimiento usa un tag compartido (``room`` o
  ``roomtype#lab``) que portan varios recursos, y el solver selecciona uno.
"""

from __future__ import annotations

from .ids import GroupId, RoomId, TeacherId

GENERIC_TEACHER = "teacher"
GENERIC_GROUP = "group"
GENERIC_ROOM = "room"


def teacher_tag(teacher_id: TeacherId) -> str:
    return f"teacher#{int(teacher_id)}"


def group_tag(group_id: GroupId) -> str:
    return f"group#{int(group_id)}"


def room_id_tag(room_id: RoomId) -> str:
    return f"room#{int(room_id)}"


def room_type_tag(room_type: str) -> str:
    return f"roomtype#{room_type}"


def equipment_tag(equipment: str) -> str:
    return f"equip#{equipment}"
