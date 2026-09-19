"""Columnas de las cuadrículas de datos maestros (`MasterDataGrid`).

Las columnas se derivan de los campos de cada entidad del modelo, así un campo
nuevo aparece solo en la UI. Aquí viven únicamente las etiquetas (es/de) y la
forma de mostrar y leer cada tipo de valor en una celda de texto.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from scheduling_platform.untis_model import (
    Department,
    MinMax,
    Room,
    SchoolClass,
    StudentGroup,
    Subject,
    Teacher,
)


class MasterKind(StrEnum):
    """Ventanas de datos maestros."""

    CLASSES = "classes"
    TEACHERS = "teachers"
    ROOMS = "rooms"
    SUBJECTS = "subjects"
    DEPARTMENTS = "departments"
    STUDENT_GROUPS = "student_groups"


#: Entidad del modelo detrás de cada ventana.
ENTITY_OF: Final[dict[MasterKind, type]] = {
    MasterKind.CLASSES: SchoolClass,
    MasterKind.TEACHERS: Teacher,
    MasterKind.ROOMS: Room,
    MasterKind.SUBJECTS: Subject,
    MasterKind.DEPARTMENTS: Department,
    MasterKind.STUDENT_GROUPS: StudentGroup,
}

#: Campo del `UntisProject` que guarda la colección de cada ventana.
COLLECTION_OF: Final[dict[MasterKind, str]] = {
    MasterKind.CLASSES: "classes",
    MasterKind.TEACHERS: "teachers",
    MasterKind.ROOMS: "rooms",
    MasterKind.SUBJECTS: "subjects",
    MasterKind.DEPARTMENTS: "departments",
    MasterKind.STUDENT_GROUPS: "student_groups",
}


class ValueType(StrEnum):
    """Cómo se muestra y se lee el valor de una celda."""

    TEXT = "text"
    INT = "int"
    OPT_INT = "opt_int"
    BOOL = "bool"
    MINMAX = "minmax"
    LIST = "list"
    OPT_TEXT = "opt_text"


#: Etiquetas `campo -> (español, alemán)`. Términos genéricos, no textos de Untis.
LABELS: Final[dict[str, tuple[str, str]]] = {
    "id": ("Nombre corto", "Kurzname"),
    "name": ("Nombre completo", "Langname"),
    "surname": ("Apellido", "Nachname"),
    "forename": ("Nombre", "Vorname"),
    "email": ("Correo", "E-Mail"),
    "text": ("Texto", "Text"),
    "time_grid": ("Rejilla", "Zeitraster"),
    "home_room": ("Aula base", "Stammraum"),
    "class_teacher": ("Profesor tutor", "Klassenlehrer"),
    "department": ("Departamento", "Abteilung"),
    "students": ("Alumnos", "Schüler"),
    "level": ("Nivel", "Stufe"),
    "periods_per_day": ("Períodos/día mín-máx", "Std./Tag min-max"),
    "lunch_break": ("Almuerzo mín-máx", "Mittagspause min-max"),
    "main_subjects_per_day": ("Mat. principales/día", "Hauptfächer/Tag"),
    "main_subjects_consecutive": ("Mat. principales seguidas", "Hauptfächer hintereinander"),
    "days_per_week_max": ("Días/semana máx", "Tage/Woche max"),
    "ntp_per_day": ("Huecos/día mín-máx", "Hohlstd./Tag min-max"),
    "ntp_per_week": ("Huecos/semana mín-máx", "Hohlstd./Woche min-max"),
    "consecutive_max": ("Períodos seguidos máx", "Std. hintereinander max"),
    "supervision_max": ("Guardias: minutos/semana máx", "Pausenaufsicht Minuten/Woche max"),
    "substitution_lock": ("Reserva para sustituir (0-9)", "Sperrvermerk (0-9)"),
    "status": ("Situación", "Status"),
    "payroll_number": ("Nº de nómina", "Personalnummer"),
    "gender": ("Género", "Geschlecht"),
    "capacity": ("Capacidad", "Kapazität"),
    "alternative_room": ("Aula alternativa", "Ausweichraum"),
    "room_weight": ("Peso de aula (0-4)", "Raumgewicht (0-4)"),
    "main_subject": ("Materia principal", "Hauptfach"),
    "not_same_day": ("No el mismo día", "Nicht am selben Tag"),
    "double_period_required": ("Doble obligatorio", "Doppelstunde Pflicht"),
    "required_room": ("Aula obligatoria", "Pflichtraum"),
    "subject_group": ("Grupo de materias", "Fächergruppe"),
    "fore_color": ("Color de texto", "Vordergrundfarbe"),
    "back_color": ("Color de fondo", "Hintergrundfarbe"),
    "subject": ("Materia", "Fach"),
    "classes": ("Clases", "Klassen"),
}

#: Campos que referencian otra entidad: la UI ofrece un desplegable.
REFERENCES: Final[dict[str, str]] = {
    "time_grid": "time_grids",
    "home_room": "rooms",
    "class_teacher": "teachers",
    "department": "departments",
    "alternative_room": "rooms",
    "required_room": "rooms",
    "subject": "subjects",
}


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """Una columna de una cuadrícula de datos maestros."""

    field: str
    label: str
    label_de: str
    value_type: ValueType
    editable: bool = True
    reference: str | None = None
    """Colección del proyecto a la que apunta (desplegable), si es una referencia."""

    def title(self, language: str = "es") -> str:
        return self.label_de if language == "de" else self.label


def _value_type(annotation: object) -> ValueType:
    if annotation is MinMax:
        return ValueType.MINMAX
    if annotation is bool:
        return ValueType.BOOL
    if annotation is int:
        return ValueType.INT
    if annotation is str:
        return ValueType.TEXT
    origen = typing.get_origin(annotation)
    argumentos = typing.get_args(annotation)
    if origen in (types.UnionType, typing.Union) and type(None) in argumentos:
        resto = [a for a in argumentos if a is not type(None)]
        if resto == [int]:
            return ValueType.OPT_INT
        if resto == [str]:
            return ValueType.OPT_TEXT
    if origen is tuple:
        return ValueType.LIST
    return ValueType.TEXT


def columns(kind: MasterKind) -> tuple[ColumnSpec, ...]:
    """Columnas de la ventana `kind`, en el orden de los campos del modelo."""
    entidad = ENTITY_OF[kind]
    pistas = typing.get_type_hints(entidad)
    resultado: list[ColumnSpec] = []
    for f in dataclasses.fields(entidad):
        es, de = LABELS.get(f.name, (f.name, f.name))
        resultado.append(
            ColumnSpec(
                field=f.name,
                label=es,
                label_de=de,
                value_type=_value_type(pistas[f.name]),
                editable=f.name != "id",
                reference=REFERENCES.get(f.name),
            )
        )
    return tuple(resultado)


# --------------------------------------------------------------------------- #
# Texto de celda <-> valor
# --------------------------------------------------------------------------- #

_TRUE = frozenset({"1", "x", "si", "sí", "s", "yes", "y", "true", "ja", "j", "verdadero"})
_FALSE = frozenset({"", "0", "no", "n", "false", "nein", "falso", "-"})


def format_value(value: object, value_type: ValueType) -> str:
    """Texto que muestra una celda."""
    if value is None:
        return ""
    if value_type is ValueType.BOOL:
        return "x" if value else ""
    if value_type is ValueType.MINMAX and isinstance(value, MinMax):
        if not value.is_set:
            return ""
        lo = "" if value.min is None else str(value.min)
        hi = "" if value.max is None else str(value.max)
        return f"{lo}-{hi}"
    if value_type is ValueType.LIST and isinstance(value, tuple):
        return ", ".join(str(v) for v in value)
    return str(value)


def parse_value(text: str, value_type: ValueType) -> object:
    """Valor tipado a partir del texto de una celda. `ValueError` si no es válido."""
    t = text.strip()
    if value_type is ValueType.TEXT:
        return t
    if value_type is ValueType.OPT_TEXT:
        return t or None
    if value_type is ValueType.INT:
        if not t:
            return 0
        return int(t)
    if value_type is ValueType.OPT_INT:
        return None if not t else int(t)
    if value_type is ValueType.BOOL:
        bajo = t.lower()
        if bajo in _TRUE:
            return True
        if bajo in _FALSE:
            return False
        raise ValueError(f"Valor sí/no no reconocido: {text!r}")
    if value_type is ValueType.MINMAX:
        if not t:
            return MinMax()
        if "-" not in t:
            n = int(t)
            return MinMax(n, n)
        lo, _, hi = t.partition("-")
        return MinMax(int(lo) if lo.strip() else None, int(hi) if hi.strip() else None)
    if value_type is ValueType.LIST:
        partes = [p.strip() for p in t.replace(";", ",").split(",")]
        return tuple(p for p in partes if p)
    raise ValueError(f"Tipo de columna desconocido: {value_type}")
