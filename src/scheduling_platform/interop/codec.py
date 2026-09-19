"""Codec del modelo Untis: `UntisProject` <-> diccionarios JSON planos, sin pérdida.

Es la única capa que conoce la *forma* serializada de cada entidad de
`untis_model`. El contenedor `.rsp` (y cualquier otro transporte JSON) se limita
a escribir y leer estos diccionarios.

Reglas del formato:

- **Sin pérdida**: se emiten *todos* los campos de cada entidad, también los que
  están en su valor por defecto. `from_dict(to_dict(x)) == x` para toda entidad
  válida (propiedad verificada con hypothesis).
- Enums como su valor de cadena, tuplas como listas, `MinMax` como
  `{"min": ..., "max": ...}` y `None` como `null`.
- **Decodificación tolerante**: las claves desconocidas se ignoran
  (compatibilidad hacia delante) y las ausentes toman el valor por defecto de la
  dataclass (compatibilidad hacia atrás). Solo los campos sin valor por defecto
  (ids, materia de una línea, ...) son obligatorios.
- Un tipo JSON incorrecto (una cadena donde va un entero, un booleano donde va un
  número) falla con `CodecError`, nunca se convierte en silencio.

Este módulo no importa `core`: solo conoce `untis_model`.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from ..untis_model import (
    Absence,
    Assignment,
    CriterionScore,
    DateScheme,
    Department,
    EntityKind,
    Evaluation,
    HalfDay,
    Holiday,
    Lesson,
    LessonLine,
    MinMax,
    PeriodDef,
    PeriodKind,
    Room,
    SchoolClass,
    SchoolInfo,
    StudentGroup,
    Subject,
    Substitution,
    SubstitutionKind,
    Supervision,
    SupervisionArea,
    Teacher,
    Term,
    TimeGrid,
    TimeRequest,
    Timetable,
    UnspecifiedKind,
    UnspecifiedRequest,
    UntisProject,
    Weighting,
)

#: Cualquier valor representable en JSON.
type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
#: Un objeto JSON.
type JsonObject = dict[str, JsonValue]

__all__ = [
    "PROJECT_SECTIONS",
    "CodecError",
    "JsonObject",
    "JsonValue",
    "assignment_from_dict",
    "assignment_to_dict",
    "criterion_score_from_dict",
    "criterion_score_to_dict",
    "date_scheme_from_dict",
    "date_scheme_to_dict",
    "department_from_dict",
    "department_to_dict",
    "evaluation_from_dict",
    "evaluation_to_dict",
    "lesson_from_dict",
    "lesson_line_from_dict",
    "lesson_line_to_dict",
    "lesson_to_dict",
    "minmax_from_dict",
    "minmax_to_dict",
    "period_from_dict",
    "period_to_dict",
    "project_from_dict",
    "project_to_dict",
    "room_from_dict",
    "room_to_dict",
    "school_class_from_dict",
    "school_class_to_dict",
    "school_info_from_dict",
    "school_info_to_dict",
    "student_group_from_dict",
    "student_group_to_dict",
    "subject_from_dict",
    "subject_to_dict",
    "teacher_from_dict",
    "teacher_to_dict",
    "term_from_dict",
    "term_to_dict",
    "time_grid_from_dict",
    "time_grid_to_dict",
    "time_request_from_dict",
    "time_request_to_dict",
    "timetable_from_dict",
    "timetable_to_dict",
    "unspecified_request_from_dict",
    "unspecified_request_to_dict",
    "weighting_from_dict",
    "weighting_to_dict",
]


class CodecError(ValueError):
    """Documento JSON con forma o tipos incompatibles con el modelo Untis."""


# --------------------------------------------------------------------------- #
# Lectores tipados de valores JSON
# --------------------------------------------------------------------------- #


def _as_object(value: JsonValue, where: str) -> JsonObject:
    if not isinstance(value, dict):
        raise CodecError(f"{where}: se esperaba un objeto JSON, llegó {type(value).__name__}")
    return value


def _as_list(value: JsonValue, where: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise CodecError(f"{where}: se esperaba una lista JSON, llegó {type(value).__name__}")
    return value


def _as_str(value: JsonValue, where: str) -> str:
    if not isinstance(value, str):
        raise CodecError(f"{where}: se esperaba texto, llegó {type(value).__name__}")
    return value


def _as_int(value: JsonValue, where: str) -> int:
    # `bool` es subclase de `int` en Python: se rechaza explícitamente.
    if isinstance(value, bool) or not isinstance(value, int):
        raise CodecError(f"{where}: se esperaba un entero, llegó {type(value).__name__}")
    return value


def _require(d: JsonObject, key: str, where: str) -> JsonValue:
    if key not in d:
        raise CodecError(f"{where}: falta el campo obligatorio {key!r}")
    return d[key]


def _req_str(d: JsonObject, key: str, where: str) -> str:
    return _as_str(_require(d, key, where), f"{where}.{key}")


def _req_int(d: JsonObject, key: str, where: str) -> int:
    return _as_int(_require(d, key, where), f"{where}.{key}")


def _str(d: JsonObject, key: str, where: str, default: str = "") -> str:
    if key not in d:
        return default
    return _as_str(d[key], f"{where}.{key}")


def _opt_str(d: JsonObject, key: str, where: str) -> str | None:
    valor = d.get(key)
    return None if valor is None else _as_str(valor, f"{where}.{key}")


def _int(d: JsonObject, key: str, where: str, default: int = 0) -> int:
    if key not in d:
        return default
    return _as_int(d[key], f"{where}.{key}")


def _opt_int(d: JsonObject, key: str, where: str) -> int | None:
    valor = d.get(key)
    return None if valor is None else _as_int(valor, f"{where}.{key}")


def _bool(d: JsonObject, key: str, where: str, default: bool = False) -> bool:
    if key not in d:
        return default
    valor = d[key]
    if not isinstance(valor, bool):
        raise CodecError(f"{where}.{key}: se esperaba un booleano, llegó {type(valor).__name__}")
    return valor


def _float(d: JsonObject, key: str, where: str, default: float = 0.0) -> float:
    if key not in d:
        return default
    valor = d[key]
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        raise CodecError(f"{where}.{key}: se esperaba un número, llegó {type(valor).__name__}")
    return float(valor)


def _str_tuple(d: JsonObject, key: str, where: str) -> tuple[str, ...]:
    if key not in d:
        return ()
    ruta = f"{where}.{key}"
    return tuple(_as_str(v, f"{ruta}[{i}]") for i, v in enumerate(_as_list(d[key], ruta)))


def _int_tuple(
    d: JsonObject, key: str, where: str, default: tuple[int, ...] = ()
) -> tuple[int, ...]:
    if key not in d:
        return default
    ruta = f"{where}.{key}"
    return tuple(_as_int(v, f"{ruta}[{i}]") for i, v in enumerate(_as_list(d[key], ruta)))


def _enum[E: StrEnum](enum_cls: type[E], value: JsonValue, where: str) -> E:
    texto = _as_str(value, where)
    try:
        return enum_cls(texto)
    except ValueError as exc:
        validos = ", ".join(m.value for m in enum_cls)
        raise CodecError(f"{where}: valor {texto!r} fuera de {{{validos}}}") from exc


def _opt_enum[E: StrEnum](d: JsonObject, key: str, where: str, enum_cls: type[E], default: E) -> E:
    if key not in d:
        return default
    return _enum(enum_cls, d[key], f"{where}.{key}")


def _minmax_field(d: JsonObject, key: str, where: str) -> MinMax:
    valor = d.get(key)
    if valor is None:
        return MinMax()
    return minmax_from_dict(_as_object(valor, f"{where}.{key}"), f"{where}.{key}")


def _items[T](
    value: JsonValue, where: str, decode: Callable[[JsonObject, str], T]
) -> tuple[T, ...]:
    """Decodifica una lista JSON de objetos con `decode`, con ruta de error."""
    lista = _as_list(value, where)
    return tuple(
        decode(_as_object(v, f"{where}[{i}]"), f"{where}[{i}]") for i, v in enumerate(lista)
    )


def _list_field[T](
    d: JsonObject, key: str, where: str, decode: Callable[[JsonObject, str], T]
) -> tuple[T, ...]:
    if key not in d or d[key] is None:
        return ()
    return _items(d[key], f"{where}.{key}", decode)


# --------------------------------------------------------------------------- #
# Tipos de apoyo
# --------------------------------------------------------------------------- #


def minmax_to_dict(value: MinMax) -> JsonObject:
    return {"min": value.min, "max": value.max}


def minmax_from_dict(d: JsonObject, where: str = "MinMax") -> MinMax:
    return MinMax(min=_opt_int(d, "min", where), max=_opt_int(d, "max", where))


# --------------------------------------------------------------------------- #
# Rejillas de tiempo
# --------------------------------------------------------------------------- #


def period_to_dict(p: PeriodDef) -> JsonObject:
    return {
        "number": p.number,
        "start": p.start,
        "end": p.end,
        "kind": p.kind.value,
        "half_day": p.half_day.value,
        "name": p.name,
    }


def period_from_dict(d: JsonObject, where: str = "PeriodDef") -> PeriodDef:
    return PeriodDef(
        number=_req_int(d, "number", where),
        start=_req_int(d, "start", where),
        end=_req_int(d, "end", where),
        kind=_opt_enum(d, "kind", where, PeriodKind, PeriodKind.LESSON),
        half_day=_opt_enum(d, "half_day", where, HalfDay, HalfDay.MORNING),
        name=_str(d, "name", where),
    )


def time_grid_to_dict(g: TimeGrid) -> JsonObject:
    return {
        "id": g.id,
        "name": g.name,
        "days": list[JsonValue](g.days),
        "periods": [period_to_dict(p) for p in g.periods],
    }


def time_grid_from_dict(d: JsonObject, where: str = "TimeGrid") -> TimeGrid:
    return TimeGrid(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        days=_int_tuple(d, "days", where, default=(1, 2, 3, 4, 5)),
        periods=_list_field(d, "periods", where, period_from_dict),
    )


# --------------------------------------------------------------------------- #
# Datos maestros
# --------------------------------------------------------------------------- #


def department_to_dict(x: Department) -> JsonObject:
    return {"id": x.id, "name": x.name}


def department_from_dict(d: JsonObject, where: str = "Department") -> Department:
    return Department(id=_req_str(d, "id", where), name=_str(d, "name", where))


def school_class_to_dict(x: SchoolClass) -> JsonObject:
    return {
        "id": x.id,
        "name": x.name,
        "time_grid": x.time_grid,
        "home_room": x.home_room,
        "class_teacher": x.class_teacher,
        "department": x.department,
        "students": x.students,
        "level": x.level,
        "periods_per_day": minmax_to_dict(x.periods_per_day),
        "lunch_break": minmax_to_dict(x.lunch_break),
        "main_subjects_per_day": x.main_subjects_per_day,
        "main_subjects_consecutive": x.main_subjects_consecutive,
        "text": x.text,
    }


def school_class_from_dict(d: JsonObject, where: str = "SchoolClass") -> SchoolClass:
    return SchoolClass(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        time_grid=_str(d, "time_grid", where),
        home_room=_opt_str(d, "home_room", where),
        class_teacher=_opt_str(d, "class_teacher", where),
        department=_opt_str(d, "department", where),
        students=_int(d, "students", where),
        level=_opt_int(d, "level", where),
        periods_per_day=_minmax_field(d, "periods_per_day", where),
        lunch_break=_minmax_field(d, "lunch_break", where),
        main_subjects_per_day=_opt_int(d, "main_subjects_per_day", where),
        main_subjects_consecutive=_opt_int(d, "main_subjects_consecutive", where),
        text=_str(d, "text", where),
    )


def teacher_to_dict(x: Teacher) -> JsonObject:
    return {
        "id": x.id,
        "name": x.name,
        "surname": x.surname,
        "forename": x.forename,
        "email": x.email,
        "department": x.department,
        "home_room": x.home_room,
        "periods_per_day": minmax_to_dict(x.periods_per_day),
        "days_per_week_max": x.days_per_week_max,
        "ntp_per_day": minmax_to_dict(x.ntp_per_day),
        "ntp_per_week": minmax_to_dict(x.ntp_per_week),
        "lunch_break": minmax_to_dict(x.lunch_break),
        "consecutive_max": x.consecutive_max,
        "supervision_max": x.supervision_max,
        "substitution_lock": x.substitution_lock,
        "text": x.text,
        "status": x.status,
        "payroll_number": x.payroll_number,
        "gender": x.gender,
    }


def teacher_from_dict(d: JsonObject, where: str = "Teacher") -> Teacher:
    return Teacher(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        surname=_str(d, "surname", where),
        forename=_str(d, "forename", where),
        email=_str(d, "email", where),
        department=_opt_str(d, "department", where),
        home_room=_opt_str(d, "home_room", where),
        periods_per_day=_minmax_field(d, "periods_per_day", where),
        days_per_week_max=_opt_int(d, "days_per_week_max", where),
        ntp_per_day=_minmax_field(d, "ntp_per_day", where),
        ntp_per_week=_minmax_field(d, "ntp_per_week", where),
        lunch_break=_minmax_field(d, "lunch_break", where),
        consecutive_max=_opt_int(d, "consecutive_max", where),
        supervision_max=_opt_int(d, "supervision_max", where),
        substitution_lock=_int(d, "substitution_lock", where),
        text=_str(d, "text", where),
        status=_str(d, "status", where),
        payroll_number=_str(d, "payroll_number", where),
        gender=_str(d, "gender", where),
    )


def room_to_dict(x: Room) -> JsonObject:
    return {
        "id": x.id,
        "name": x.name,
        "capacity": x.capacity,
        "alternative_room": x.alternative_room,
        "room_weight": x.room_weight,
        "department": x.department,
        "text": x.text,
    }


def room_from_dict(d: JsonObject, where: str = "Room") -> Room:
    return Room(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        capacity=_opt_int(d, "capacity", where),
        alternative_room=_opt_str(d, "alternative_room", where),
        room_weight=_int(d, "room_weight", where),
        department=_opt_str(d, "department", where),
        text=_str(d, "text", where),
    )


def subject_to_dict(x: Subject) -> JsonObject:
    return {
        "id": x.id,
        "name": x.name,
        "main_subject": x.main_subject,
        "not_same_day": x.not_same_day,
        "double_period_required": x.double_period_required,
        "required_room": x.required_room,
        "subject_group": x.subject_group,
        "fore_color": x.fore_color,
        "back_color": x.back_color,
    }


def subject_from_dict(d: JsonObject, where: str = "Subject") -> Subject:
    return Subject(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        main_subject=_bool(d, "main_subject", where),
        not_same_day=_bool(d, "not_same_day", where),
        double_period_required=_bool(d, "double_period_required", where),
        required_room=_opt_str(d, "required_room", where),
        subject_group=_opt_str(d, "subject_group", where),
        fore_color=_str(d, "fore_color", where),
        back_color=_str(d, "back_color", where),
    )


def student_group_to_dict(x: StudentGroup) -> JsonObject:
    return {
        "id": x.id,
        "name": x.name,
        "subject": x.subject,
        "classes": list[JsonValue](x.classes),
        "students": x.students,
    }


def student_group_from_dict(d: JsonObject, where: str = "StudentGroup") -> StudentGroup:
    return StudentGroup(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        subject=_opt_str(d, "subject", where),
        classes=_str_tuple(d, "classes", where),
        students=_int(d, "students", where),
    )


def term_to_dict(x: Term) -> JsonObject:
    return {
        "id": x.id,
        "name": x.name,
        "begin": x.begin,
        "end": x.end,
        "time_grid": x.time_grid,
    }


def term_from_dict(d: JsonObject, where: str = "Term") -> Term:
    return Term(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        begin=_str(d, "begin", where),
        end=_str(d, "end", where),
        time_grid=_opt_str(d, "time_grid", where),
    )


def date_scheme_to_dict(x: DateScheme) -> JsonObject:
    return {"id": x.id, "pattern": x.pattern, "periodic_weeks": x.periodic_weeks}


def date_scheme_from_dict(d: JsonObject, where: str = "DateScheme") -> DateScheme:
    return DateScheme(
        id=_req_str(d, "id", where),
        pattern=_str(d, "pattern", where),
        periodic_weeks=_str(d, "periodic_weeks", where),
    )


def school_info_to_dict(x: SchoolInfo) -> JsonObject:
    return {
        "name": x.name,
        "school_year_begin": x.school_year_begin,
        "school_year_end": x.school_year_end,
        "header1": x.header1,
        "header2": x.header2,
        "footer": x.footer,
        "term_name": x.term_name,
        "school_type": x.school_type,
        "term_begin": x.term_begin,
        "term_end": x.term_end,
        "first_period": x.first_period,
    }


def school_info_from_dict(d: JsonObject, where: str = "SchoolInfo") -> SchoolInfo:
    return SchoolInfo(
        name=_str(d, "name", where),
        school_year_begin=_str(d, "school_year_begin", where),
        school_year_end=_str(d, "school_year_end", where),
        header1=_str(d, "header1", where),
        header2=_str(d, "header2", where),
        footer=_str(d, "footer", where),
        term_name=_str(d, "term_name", where),
        school_type=_str(d, "school_type", where),
        term_begin=_str(d, "term_begin", where),
        term_end=_str(d, "term_end", where),
        first_period=_int(d, "first_period", where, default=1),
    )


# --------------------------------------------------------------------------- #
# Lecciones
# --------------------------------------------------------------------------- #


def lesson_line_to_dict(x: LessonLine) -> JsonObject:
    return {
        "subject": x.subject,
        "teacher": x.teacher,
        "classes": list[JsonValue](x.classes),
        "student_group": x.student_group,
        "room": x.room,
        "alternative_room": x.alternative_room,
        "weekly_value": x.weekly_value,
    }


def lesson_line_from_dict(d: JsonObject, where: str = "LessonLine") -> LessonLine:
    return LessonLine(
        subject=_req_str(d, "subject", where),
        teacher=_opt_str(d, "teacher", where),
        classes=_str_tuple(d, "classes", where),
        student_group=_opt_str(d, "student_group", where),
        room=_opt_str(d, "room", where),
        alternative_room=_opt_str(d, "alternative_room", where),
        weekly_value=_float(d, "weekly_value", where),
    )


def lesson_to_dict(x: Lesson) -> JsonObject:
    return {
        "number": x.number,
        "lines": [lesson_line_to_dict(line) for line in x.lines],
        "periods_per_week": x.periods_per_week,
        "time_grid": x.time_grid,
        "double_periods": minmax_to_dict(x.double_periods),
        "block": list[JsonValue](x.block),
        "fixed": x.fixed,
        "ignore": x.ignore,
        "not_same_day": x.not_same_day,
        "sequence_after": x.sequence_after,
        "weekly_value": x.weekly_value,
        "term": x.term,
        "lesson_group": x.lesson_group,
        "effective_begin": x.effective_begin,
        "effective_end": x.effective_end,
        "occurrence": x.occurrence,
    }


def lesson_from_dict(d: JsonObject, where: str = "Lesson") -> Lesson:
    return Lesson(
        number=_req_int(d, "number", where),
        lines=_items(_require(d, "lines", where), f"{where}.lines", lesson_line_from_dict),
        periods_per_week=_req_int(d, "periods_per_week", where),
        time_grid=_str(d, "time_grid", where),
        double_periods=_minmax_field(d, "double_periods", where),
        block=_int_tuple(d, "block", where),
        fixed=_bool(d, "fixed", where),
        ignore=_bool(d, "ignore", where),
        not_same_day=_bool(d, "not_same_day", where),
        sequence_after=_opt_str(d, "sequence_after", where),
        weekly_value=_float(d, "weekly_value", where),
        term=_opt_str(d, "term", where),
        lesson_group=_opt_str(d, "lesson_group", where),
        effective_begin=_str(d, "effective_begin", where),
        effective_end=_str(d, "effective_end", where),
        occurrence=_str(d, "occurrence", where),
    )


# --------------------------------------------------------------------------- #
# Deseos de tiempo
# --------------------------------------------------------------------------- #


def time_request_to_dict(x: TimeRequest) -> JsonObject:
    return {
        "entity_kind": x.entity_kind.value,
        "entity_id": x.entity_id,
        "value": x.value,
        "day": x.day,
        "period": x.period,
    }


def time_request_from_dict(d: JsonObject, where: str = "TimeRequest") -> TimeRequest:
    return TimeRequest(
        entity_kind=_enum(EntityKind, _require(d, "entity_kind", where), f"{where}.entity_kind"),
        entity_id=_req_str(d, "entity_id", where),
        value=_req_int(d, "value", where),
        day=_opt_int(d, "day", where),
        period=_opt_int(d, "period", where),
    )


def unspecified_request_to_dict(x: UnspecifiedRequest) -> JsonObject:
    return {
        "entity_kind": x.entity_kind.value,
        "entity_id": x.entity_id,
        "kind": x.kind.value,
        "count": x.count,
    }


def unspecified_request_from_dict(
    d: JsonObject, where: str = "UnspecifiedRequest"
) -> UnspecifiedRequest:
    return UnspecifiedRequest(
        entity_kind=_enum(EntityKind, _require(d, "entity_kind", where), f"{where}.entity_kind"),
        entity_id=_req_str(d, "entity_id", where),
        kind=_enum(UnspecifiedKind, _require(d, "kind", where), f"{where}.kind"),
        count=_int(d, "count", where, default=1),
    )


# --------------------------------------------------------------------------- #
# Ponderación
# --------------------------------------------------------------------------- #


def weighting_to_dict(x: Weighting) -> JsonObject:
    return dict[str, JsonValue](x.as_dict())


def weighting_from_dict(d: JsonObject, where: str = "Weighting") -> Weighting:
    """Criterios desconocidos se ignoran; los ausentes quedan en su valor por defecto."""
    validos = set(Weighting.criteria())
    return Weighting.from_dict(
        {k: _as_int(v, f"{where}.{k}") for k, v in d.items() if k in validos}
    )


# --------------------------------------------------------------------------- #
# Horarios
# --------------------------------------------------------------------------- #


def assignment_to_dict(x: Assignment) -> JsonObject:
    return {
        "lesson_number": x.lesson_number,
        "line": x.line,
        "day": x.day,
        "period": x.period,
        "room": x.room,
        "fixed": x.fixed,
        "manual": x.manual,
    }


def assignment_from_dict(d: JsonObject, where: str = "Assignment") -> Assignment:
    return Assignment(
        lesson_number=_req_int(d, "lesson_number", where),
        line=_int(d, "line", where),
        day=_req_int(d, "day", where),
        period=_req_int(d, "period", where),
        room=_opt_str(d, "room", where),
        fixed=_bool(d, "fixed", where),
        manual=_bool(d, "manual", where),
    )


def criterion_score_to_dict(x: CriterionScore) -> JsonObject:
    return {"criterion": x.criterion, "violations": x.violations, "weight": x.weight}


def criterion_score_from_dict(d: JsonObject, where: str = "CriterionScore") -> CriterionScore:
    return CriterionScore(
        criterion=_req_str(d, "criterion", where),
        violations=_req_int(d, "violations", where),
        weight=_req_int(d, "weight", where),
    )


def evaluation_to_dict(x: Evaluation) -> JsonObject:
    return {
        "unplaced_periods": x.unplaced_periods,
        "clashes": x.clashes,
        "scores": [criterion_score_to_dict(s) for s in x.scores],
    }


def evaluation_from_dict(d: JsonObject, where: str = "Evaluation") -> Evaluation:
    return Evaluation(
        unplaced_periods=_int(d, "unplaced_periods", where),
        clashes=_int(d, "clashes", where),
        scores=_list_field(d, "scores", where, criterion_score_from_dict),
    )


def timetable_to_dict(x: Timetable) -> JsonObject:
    return {
        "id": x.id,
        "name": x.name,
        "assignments": [assignment_to_dict(a) for a in x.assignments],
        "evaluation": evaluation_to_dict(x.evaluation),
    }


def timetable_from_dict(d: JsonObject, where: str = "Timetable") -> Timetable:
    evaluacion = d.get("evaluation")
    return Timetable(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        assignments=_list_field(d, "assignments", where, assignment_from_dict),
        evaluation=(
            Evaluation()
            if evaluacion is None
            else evaluation_from_dict(
                _as_object(evaluacion, f"{where}.evaluation"), f"{where}.evaluation"
            )
        ),
    )


# --------------------------------------------------------------------------- #
# Guardias de recreo, calendario, ausencias y sustituciones
# --------------------------------------------------------------------------- #


def supervision_area_to_dict(x: SupervisionArea) -> JsonObject:
    return {
        "id": x.id,
        "name": x.name,
        "time_grid": x.time_grid,
        "weight": x.weight,
        "text": x.text,
    }


def supervision_area_from_dict(d: JsonObject, where: str = "SupervisionArea") -> SupervisionArea:
    return SupervisionArea(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        time_grid=_str(d, "time_grid", where),
        weight=_int(d, "weight", where, default=1),
        text=_str(d, "text", where),
    )


def supervision_to_dict(x: Supervision) -> JsonObject:
    return {
        "area": x.area,
        "day": x.day,
        "period": x.period,
        "teacher": x.teacher,
        "fixed": x.fixed,
        "minutes": x.minutes,
    }


def supervision_from_dict(d: JsonObject, where: str = "Supervision") -> Supervision:
    return Supervision(
        area=_req_str(d, "area", where),
        day=_int(d, "day", where),
        period=_int(d, "period", where),
        teacher=_str(d, "teacher", where),
        fixed=_bool(d, "fixed", where),
        minutes=_int(d, "minutes", where),
    )


def holiday_to_dict(x: Holiday) -> JsonObject:
    return {"id": x.id, "name": x.name, "begin": x.begin, "end": x.end}


def holiday_from_dict(d: JsonObject, where: str = "Holiday") -> Holiday:
    return Holiday(
        id=_req_str(d, "id", where),
        name=_str(d, "name", where),
        begin=_str(d, "begin", where),
        end=_str(d, "end", where),
    )


def absence_to_dict(x: Absence) -> JsonObject:
    return {
        "id": x.id,
        "entity_kind": x.entity_kind.value,
        "entity_id": x.entity_id,
        "begin": x.begin,
        "end": x.end,
        "first_period": x.first_period,
        "last_period": x.last_period,
        "reason": x.reason,
        "text": x.text,
    }


def absence_from_dict(d: JsonObject, where: str = "Absence") -> Absence:
    return Absence(
        id=_req_str(d, "id", where),
        entity_kind=_enum(EntityKind, _require(d, "entity_kind", where), f"{where}.entity_kind"),
        entity_id=_req_str(d, "entity_id", where),
        begin=_req_str(d, "begin", where),
        end=_str(d, "end", where),
        first_period=_opt_int(d, "first_period", where),
        last_period=_opt_int(d, "last_period", where),
        reason=_str(d, "reason", where),
        text=_str(d, "text", where),
    )


def substitution_to_dict(x: Substitution) -> JsonObject:
    return {
        "id": x.id,
        "date": x.date,
        "period": x.period,
        "lesson_number": x.lesson_number,
        "kind": x.kind.value,
        "absent_teacher": x.absent_teacher,
        "teacher": x.teacher,
        "room": x.room,
        "absence": x.absence,
        "note": x.note,
    }


def substitution_from_dict(d: JsonObject, where: str = "Substitution") -> Substitution:
    return Substitution(
        id=_req_str(d, "id", where),
        date=_req_str(d, "date", where),
        period=_int(d, "period", where),
        lesson_number=_int(d, "lesson_number", where),
        kind=_opt_enum(d, "kind", where, SubstitutionKind, SubstitutionKind.SUBSTITUTION),
        absent_teacher=_str(d, "absent_teacher", where),
        teacher=_str(d, "teacher", where),
        room=_str(d, "room", where),
        absence=_str(d, "absence", where),
        note=_str(d, "note", where),
    )


# --------------------------------------------------------------------------- #
# Proyecto
# --------------------------------------------------------------------------- #

#: Secciones de primer nivel de `project_to_dict`, en el orden del modelo.
#: `.rsp` guarda cada una en su propio archivo.
PROJECT_SECTIONS: tuple[str, ...] = (
    "school",
    "time_grids",
    "departments",
    "classes",
    "teachers",
    "rooms",
    "subjects",
    "student_groups",
    "terms",
    "lessons",
    "time_requests",
    "unspecified_requests",
    "weighting",
    "timetables",
    "date_schemes",
    "supervision_areas",
    "supervisions",
    "holidays",
    "absences",
    "substitutions",
)


def project_to_dict(project: UntisProject) -> JsonObject:
    """Proyecto completo como un objeto JSON con una clave por sección."""
    return {
        "school": school_info_to_dict(project.school),
        "time_grids": [time_grid_to_dict(x) for x in project.time_grids],
        "departments": [department_to_dict(x) for x in project.departments],
        "classes": [school_class_to_dict(x) for x in project.classes],
        "teachers": [teacher_to_dict(x) for x in project.teachers],
        "rooms": [room_to_dict(x) for x in project.rooms],
        "subjects": [subject_to_dict(x) for x in project.subjects],
        "student_groups": [student_group_to_dict(x) for x in project.student_groups],
        "terms": [term_to_dict(x) for x in project.terms],
        "lessons": [lesson_to_dict(x) for x in project.lessons],
        "time_requests": [time_request_to_dict(x) for x in project.time_requests],
        "unspecified_requests": [
            unspecified_request_to_dict(x) for x in project.unspecified_requests
        ],
        "weighting": weighting_to_dict(project.weighting),
        "timetables": [timetable_to_dict(x) for x in project.timetables],
        "date_schemes": [date_scheme_to_dict(x) for x in project.date_schemes],
        "supervision_areas": [supervision_area_to_dict(x) for x in project.supervision_areas],
        "supervisions": [supervision_to_dict(x) for x in project.supervisions],
        "holidays": [holiday_to_dict(x) for x in project.holidays],
        "absences": [absence_to_dict(x) for x in project.absences],
        "substitutions": [substitution_to_dict(x) for x in project.substitutions],
    }


def project_from_dict(d: JsonObject, where: str = "UntisProject") -> UntisProject:
    """Inversa de `project_to_dict`; secciones ausentes quedan vacías/por defecto."""
    escuela = d.get("school")
    ponderacion = d.get("weighting")
    return UntisProject(
        school=(
            SchoolInfo()
            if escuela is None
            else school_info_from_dict(_as_object(escuela, f"{where}.school"), f"{where}.school")
        ),
        time_grids=_list_field(d, "time_grids", where, time_grid_from_dict),
        departments=_list_field(d, "departments", where, department_from_dict),
        classes=_list_field(d, "classes", where, school_class_from_dict),
        teachers=_list_field(d, "teachers", where, teacher_from_dict),
        rooms=_list_field(d, "rooms", where, room_from_dict),
        subjects=_list_field(d, "subjects", where, subject_from_dict),
        student_groups=_list_field(d, "student_groups", where, student_group_from_dict),
        terms=_list_field(d, "terms", where, term_from_dict),
        lessons=_list_field(d, "lessons", where, lesson_from_dict),
        time_requests=_list_field(d, "time_requests", where, time_request_from_dict),
        unspecified_requests=_list_field(
            d, "unspecified_requests", where, unspecified_request_from_dict
        ),
        weighting=(
            Weighting()
            if ponderacion is None
            else weighting_from_dict(
                _as_object(ponderacion, f"{where}.weighting"), f"{where}.weighting"
            )
        ),
        timetables=_list_field(d, "timetables", where, timetable_from_dict),
        date_schemes=_list_field(d, "date_schemes", where, date_scheme_from_dict),
        supervision_areas=_list_field(d, "supervision_areas", where, supervision_area_from_dict),
        supervisions=_list_field(d, "supervisions", where, supervision_from_dict),
        holidays=_list_field(d, "holidays", where, holiday_from_dict),
        absences=_list_field(d, "absences", where, absence_from_dict),
        substitutions=_list_field(d, "substitutions", where, substitution_from_dict),
    )
