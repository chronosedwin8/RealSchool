"""Lectura y escritura del XmlInterface 3.x de Untis sobre `UntisProject`.

Sustituye al parser plano de `scheduling_platform.untis.parser`: aquí el XML se
traduce directamente al modelo de dominio (`untis_model`), sin entidades
intermedias. Reglas de traducción, verificadas sobre el export real:

- Un id `LS_<nº><línea>` es una línea de acople: `LS_401` es la línea 1 de la
  lección 40. Las líneas de un mismo número forman la `Lesson`; el acople no se
  infiere de ninguna otra forma.
- **Contrato de ids**: el id de una entidad del modelo es el *nombre corto* de
  Untis (`K1A`), el mismo que usan los archivos GPU y MiUntisWeb. XmlInterface
  antepone un prefijo por tipo (`CL_K1A`, `TR_T028`, `SU_MATK1`, `RM_P 11`,
  `DP_B`, `SG_MATK1_K1A`, `UG_.`): al leer se quita del id de la entidad y de
  toda referencia a ella; al escribir se vuelve a poner (ver `ID_PREFIXES`).
  Lectura tolerante: un id sin su prefijo esperado se conserva tal cual; al
  escribirlo recibe el prefijo, así que la ida y vuelta del modelo es exacta.
- `lesson_classes` lleva varios ids separados por espacios, pero un id puede
  contener espacios (`CL_12-GIB 2`): se corta solo ante un nuevo prefijo `CL_`
  y *después* se quita el prefijo de cada trozo.
- `teacher_value` es un decimal de coma fija con cinco cifras (`500000` = 5,0).
- `block` se guarda tal cual en `Lesson.block`; los dobles exigidos se deducen
  con `double_periods_from_block`.
- `times/time` es el horario que Untis generó: cada `time` es una `Assignment`
  y todas van a un único `Timetable(id="untis")`.
- Las `timeperiods` tienen la misma hora de reloj todos los días dentro de una
  rejilla, así que cada rejilla es una `TimeGrid` indexada por período.

Una línea sin materia es válida en Untis (p. ej. guardias), pero `LessonLine`
exige materia: se usa la materia comodín `MISSING_SUBJECT_ID`, que se añade a
las materias del proyecto solo si alguna línea la necesita y que nunca se
escribe de vuelta al XML. Así el diagnóstico queda limpio y la ida y vuelta es
exacta.

Todo dato del export real tiene sitio en el modelo. Lo que no se guarda es
metadato derivado que se regenera al escribir (`REGENERATED_FIELDS`) o secciones
que el modelo no representa y que llegan vacías en los exports reales
(`DROPPED_FIELDS`); `scripts/xml_fields_inventory.py` verifica la cobertura.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Final

from scheduling_platform.untis_model import (
    Assignment,
    DateScheme,
    Department,
    HalfDay,
    Lesson,
    LessonLine,
    PeriodDef,
    PeriodKind,
    Room,
    SchoolClass,
    SchoolInfo,
    StudentGroup,
    Subject,
    Teacher,
    TimeGrid,
    Timetable,
    UntisProject,
    build_lesson_id,
    double_periods_from_block,
    hhmm_to_minutes,
    minutes_to_hhmm,
    split_lesson_id,
)

#: Espacio de nombres del XmlInterface de Untis.
UNTIS_NS: Final = "https://untis.at/untis/XmlInterface"
#: Versión del XmlInterface que declara el documento escrito.
XML_VERSION: Final = "3.1"
#: Espacio de nombres XML Schema y ubicación del XSD que declara Untis.
XSI_NS: Final = "http://www.w3.org/2001/XMLSchema-instance"
XSD_LOCATION: Final = (
    "https://untis.at/untis/XmlInterface "
    "https://www.untis.at/fileadmin/downloads/xsd/XmlInterface-3.1.xsd"
)

#: Prefijos de id de XmlInterface por tipo de entidad. El id del modelo es el
#: nombre corto sin prefijo; las lecciones (`LS_`) van aparte (`split_lesson_id`)
#: y las rejillas no llevan prefijo.
CLASS_PREFIX: Final = "CL_"
TEACHER_PREFIX: Final = "TR_"
SUBJECT_PREFIX: Final = "SU_"
ROOM_PREFIX: Final = "RM_"
DEPARTMENT_PREFIX: Final = "DP_"
STUDENT_GROUP_PREFIX: Final = "SG_"
DATE_SCHEME_PREFIX: Final = "UG_"
ID_PREFIXES: Final = (
    CLASS_PREFIX,
    TEACHER_PREFIX,
    SUBJECT_PREFIX,
    ROOM_PREFIX,
    DEPARTMENT_PREFIX,
    STUDENT_GROUP_PREFIX,
    DATE_SCHEME_PREFIX,
)

#: Id del horario que guarda las colocaciones de `times/time`.
UNTIS_TIMETABLE_ID: Final = "untis"
UNTIS_TIMETABLE_NAME: Final = "Untis"

#: Materia comodín (id del modelo) para las líneas que en Untis no tienen materia.
MISSING_SUBJECT_ID: Final = "?"
MISSING_SUBJECT_NAME: Final = "(sin materia)"

#: Escala de coma fija de `teacher_value` (`500000` = 5,0).
TEACHER_VALUE_SCALE: Final = 100_000

#: A partir de esta hora (minutos) un período cuenta como de tarde.
AFTERNOON_START: Final = 12 * 60

#: Metadatos que no se guardan en el modelo porque se derivan de él o del
#: momento de la exportación: se regeneran al escribir. Rutas relativas al
#: elemento que las contiene (`time/assigned_starttime`) o absolutas desde
#: `document`.
REGENERATED_FIELDS: Final = (
    "document/@date",
    "document/@time",
    "document/@version",
    "document/@xsi:schemaLocation",
    "time/assigned_starttime",
    "time/assigned_endtime",
    "timeperiod/@id",
)

#: Secciones del XmlInterface sin sitio en `untis_model`: si trajeran datos se
#: perderían. En los exports reales llegan vacías (lo comprueba
#: `scripts/xml_fields_inventory.py`) y se escriben vacías.
DROPPED_FIELDS: Final = (
    "holidays",
    "descriptions",
    "students",
)


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #


class _Reader:
    """Acceso a los hijos de un documento con o sin espacio de nombres."""

    def __init__(self, root: ET.Element) -> None:
        tag = root.tag
        self._ns = tag[: tag.index("}") + 1] if tag.startswith("{") else ""

    def q(self, tag: str) -> str:
        """Nombre cualificado de `tag` en el espacio de nombres del documento."""
        return f"{self._ns}{tag}"

    def all(self, element: ET.Element, path: str) -> list[ET.Element]:
        """Elementos bajo `path` (`a/b`), en orden de documento."""
        return element.findall("/".join(self.q(p) for p in path.split("/")))

    def text(self, element: ET.Element | None, tag: str) -> str:
        """Texto de un hijo, sin espacios alrededor; `""` si falta o está vacío."""
        if element is None:
            return ""
        node = element.find(self.q(tag))
        if node is None or node.text is None:
            return ""
        return node.text.strip()

    def ref(self, element: ET.Element, tag: str, prefix: str) -> str | None:
        """Id sin prefijo de un hijo de referencia (`<class_room id="RM_1"/>` -> `1`)."""
        node = element.find(self.q(tag))
        if node is None:
            return None
        valor = node.get("id", "").strip()
        return strip_prefix(valor, prefix) if valor else None

    def refs(self, element: ET.Element, tag: str, prefix: str) -> tuple[str, ...]:
        """Ids sin prefijo de una lista separada por espacios, sin repetir."""
        node = element.find(self.q(tag))
        if node is None:
            return ()
        partes = split_refs(node.get("id", ""))
        return tuple(dict.fromkeys(strip_prefix(p, prefix) for p in partes))


def strip_prefix(raw: str, prefix: str) -> str:
    """Id del modelo a partir del id XmlInterface: `CL_K1A` -> `K1A`.

    Tolerante: un id sin el prefijo esperado (o que sea solo el prefijo) se
    devuelve sin cambios.
    """
    if raw.startswith(prefix) and len(raw) > len(prefix):
        return raw[len(prefix) :]
    return raw


def add_prefix(ident: str, prefix: str) -> str:
    """Id XmlInterface a partir del id del modelo: `K1A` -> `CL_K1A`."""
    return f"{prefix}{ident}"


def split_refs(raw: str) -> list[str]:
    """Parte una lista de ids de Untis separada por espacios.

    Los ids pueden llevar espacios dentro (`CL_12-GIB 2`), así que solo se corta
    en el espacio que precede a un nuevo id con el mismo prefijo que el primero
    (`CL_`, `SG_`...): `"CL_12-GIB 2 CL_12-DSDA"` -> `["CL_12-GIB 2", "CL_12-DSDA"]`.
    Sin prefijo reconocible se corta en cada espacio. Los trozos conservan el
    prefijo: quitarlo es cosa de `strip_prefix`, una vez partida la lista.
    """
    texto = raw.strip()
    if not texto:
        return []
    primero = texto.split()[0]
    if "_" not in primero:
        return texto.split()
    prefijo = primero[: primero.index("_") + 1]
    return [parte.strip() for parte in re.split(rf"\s+(?={re.escape(prefijo)})", texto)]


def _entity_id(element: ET.Element, prefix: str) -> str:
    """Id del modelo de un elemento de datos maestros (`<class id="CL_K1A">`)."""
    return strip_prefix(element.get("id", "").strip(), prefix)


def _int(raw: str, default: int = 0) -> int:
    return int(raw) if raw else default


def _read_school(r: _Reader, root: ET.Element) -> SchoolInfo:
    general = root.find(r.q("general"))
    return SchoolInfo(
        name=r.text(general, "schoolname"),
        school_year_begin=r.text(general, "schoolyearbegindate"),
        school_year_end=r.text(general, "schoolyearenddate"),
        header1=r.text(general, "header1"),
        header2=r.text(general, "header2"),
        footer=r.text(general, "footer"),
        term_name=r.text(general, "termname"),
        school_type=r.text(general, "schooltype"),
        term_begin=r.text(general, "termbegindate"),
        term_end=r.text(general, "termenddate"),
    )


def _read_time_grids(r: _Reader, root: ET.Element) -> tuple[TimeGrid, ...]:
    """Agrupa las `timeperiods` por rejilla; exige la misma hora todos los días."""
    dias: dict[str, set[int]] = {}
    relojes: dict[str, dict[int, tuple[int, int]]] = {}
    for tp in r.all(root, "timeperiods/timeperiod"):
        grid = r.text(tp, "timegrid")
        dia = _int(r.text(tp, "day"))
        numero = _int(r.text(tp, "period"))
        reloj = (hhmm_to_minutes(r.text(tp, "starttime")), hhmm_to_minutes(r.text(tp, "endtime")))
        dias.setdefault(grid, set()).add(dia)
        previo = relojes.setdefault(grid, {}).setdefault(numero, reloj)
        if previo != reloj:
            raise ValueError(
                f"Rejilla {grid!r}: el período {numero} cambia de hora según el día "
                f"({previo} frente a {reloj}); el modelo no admite rejillas así."
            )

    rejillas: list[TimeGrid] = []
    for grid, por_periodo in relojes.items():
        periodos = tuple(
            PeriodDef(
                number=numero,
                start=inicio,
                end=fin,
                kind=PeriodKind.LESSON,
                half_day=HalfDay.AFTERNOON if inicio >= AFTERNOON_START else HalfDay.MORNING,
            )
            for numero, (inicio, fin) in sorted(por_periodo.items())
        )
        rejillas.append(
            TimeGrid(id=grid, name=grid, days=tuple(sorted(dias[grid])), periods=periodos)
        )
    return tuple(rejillas)


def _read_departments(r: _Reader, root: ET.Element) -> tuple[Department, ...]:
    return tuple(
        Department(id=_entity_id(d, DEPARTMENT_PREFIX), name=r.text(d, "longname"))
        for d in r.all(root, "departments/department")
    )


def _read_classes(r: _Reader, root: ET.Element) -> tuple[SchoolClass, ...]:
    return tuple(
        SchoolClass(
            id=_entity_id(c, CLASS_PREFIX),
            name=r.text(c, "longname"),
            time_grid=r.text(c, "timegrid"),
            home_room=r.ref(c, "class_room", ROOM_PREFIX),
            department=r.ref(c, "class_department", DEPARTMENT_PREFIX),
            text=r.text(c, "text"),
        )
        for c in r.all(root, "classes/class")
    )


def _read_teachers(r: _Reader, root: ET.Element) -> tuple[Teacher, ...]:
    return tuple(
        Teacher(
            id=_entity_id(t, TEACHER_PREFIX),
            surname=r.text(t, "surname"),
            forename=r.text(t, "forename"),
            email=r.text(t, "email"),
            department=r.ref(t, "teacher_department", DEPARTMENT_PREFIX),
            text=r.text(t, "text"),
            status=r.text(t, "status"),
            payroll_number=r.text(t, "payrollnumber"),
            gender=r.text(t, "gender"),
        )
        for t in r.all(root, "teachers/teacher")
    )


def _read_rooms(r: _Reader, root: ET.Element) -> tuple[Room, ...]:
    return tuple(
        Room(
            id=_entity_id(a, ROOM_PREFIX),
            name=r.text(a, "longname"),
            department=r.ref(a, "room_department", DEPARTMENT_PREFIX),
            text=r.text(a, "text"),
        )
        for a in r.all(root, "rooms/room")
    )


def _read_subjects(r: _Reader, root: ET.Element) -> tuple[Subject, ...]:
    return tuple(
        Subject(
            id=_entity_id(s, SUBJECT_PREFIX),
            name=r.text(s, "longname"),
            fore_color=r.text(s, "forecolor"),
            back_color=r.text(s, "backcolor"),
        )
        for s in r.all(root, "subjects/subject")
    )


def _read_student_groups(r: _Reader, root: ET.Element) -> tuple[StudentGroup, ...]:
    grupos: list[StudentGroup] = []
    for g in r.all(root, "studentgroups/studentgroup"):
        clases = (_entity_id(c, CLASS_PREFIX) for c in r.all(g, "classes/class"))
        grupos.append(
            StudentGroup(
                id=_entity_id(g, STUDENT_GROUP_PREFIX),
                subject=r.ref(g, "subject", SUBJECT_PREFIX),
                classes=tuple(dict.fromkeys(c for c in clases if c)),
            )
        )
    return tuple(grupos)


def _read_date_schemes(r: _Reader, root: ET.Element) -> tuple[DateScheme, ...]:
    return tuple(
        DateScheme(
            id=_entity_id(e, DATE_SCHEME_PREFIX),
            pattern=r.text(e, "date_scheme"),
            periodic_weeks=r.text(e, "periodic_weeks"),
        )
        for e in r.all(root, "lesson_date_schemes/lesson_date_scheme")
    )


def _parse_block(raw: str) -> tuple[int, ...]:
    """`"2,2"` -> `(2, 2)`; vacío -> `()`."""
    return tuple(int(parte) for parte in raw.split(",") if parte.strip())


def _parse_teacher_value(raw: str) -> float:
    """`"500000"` -> `5.0`."""
    return int(raw) / TEACHER_VALUE_SCALE if raw else 0.0


def _read_line(r: _Reader, element: ET.Element, lesson_id: str) -> LessonLine:
    grupos = r.refs(element, "lesson_studentgroups", STUDENT_GROUP_PREFIX)
    if len(grupos) > 1:
        raise ValueError(
            f"{lesson_id}: {len(grupos)} grupos de alumnos en una línea; "
            "el modelo admite uno por línea."
        )
    return LessonLine(
        subject=r.ref(element, "lesson_subject", SUBJECT_PREFIX) or MISSING_SUBJECT_ID,
        teacher=r.ref(element, "lesson_teacher", TEACHER_PREFIX),
        classes=r.refs(element, "lesson_classes", CLASS_PREFIX),
        student_group=grupos[0] if grupos else None,
        weekly_value=_parse_teacher_value(r.text(element, "teacher_value")),
    )


def _read_lessons(
    r: _Reader, root: ET.Element
) -> tuple[tuple[Lesson, ...], tuple[Assignment, ...]]:
    """Agrupa las líneas por nº de lección y extrae sus colocaciones."""
    por_numero: dict[int, dict[int, ET.Element]] = {}
    for element in r.all(root, "lessons/lesson"):
        lesson_id = element.get("id", "")
        numero, linea = split_lesson_id(lesson_id)
        lineas = por_numero.setdefault(numero, {})
        if linea in lineas:
            raise ValueError(f"Id de lección repetido: {lesson_id!r}")
        lineas[linea] = element

    lecciones: list[Lesson] = []
    colocaciones: list[Assignment] = []
    for numero, lineas in por_numero.items():
        indices = sorted(lineas)
        if indices != list(range(len(indices))):
            raise ValueError(
                f"Lección {numero}: líneas no contiguas {indices}; "
                "se esperaban 0..n-1 como en los exports de Untis."
            )
        elementos = [lineas[i] for i in indices]
        primera = elementos[0]
        periodos = _int(r.text(primera, "periods"))
        block = _parse_block(r.text(primera, "block"))
        lecciones.append(
            Lesson(
                number=numero,
                lines=tuple(
                    _read_line(r, e, build_lesson_id(numero, i)) for i, e in enumerate(elementos)
                ),
                periods_per_week=periodos,
                time_grid=r.text(primera, "timegrid"),
                double_periods=double_periods_from_block(block, periodos),
                block=block,
                effective_begin=r.text(primera, "effectivebegindate"),
                effective_end=r.text(primera, "effectiveenddate"),
                occurrence=r.text(primera, "occurence"),
            )
        )
        for i, e in enumerate(elementos):
            for t in r.all(e, "times/time"):
                colocaciones.append(
                    Assignment(
                        lesson_number=numero,
                        line=i,
                        day=_int(r.text(t, "assigned_day")),
                        period=_int(r.text(t, "assigned_period")),
                        room=r.ref(t, "assigned_room", ROOM_PREFIX),
                    )
                )
    return tuple(lecciones), tuple(colocaciones)


def read_xml(path: str | Path) -> UntisProject:
    """Lee un export XmlInterface 3.x de Untis y devuelve el proyecto."""
    root = ET.parse(Path(path)).getroot()
    r = _Reader(root)

    lecciones, colocaciones = _read_lessons(r, root)
    materias = _read_subjects(r, root)
    sin_materia = any(ln.subject == MISSING_SUBJECT_ID for le in lecciones for ln in le.lines)
    if sin_materia and all(s.id != MISSING_SUBJECT_ID for s in materias):
        materias = (*materias, Subject(id=MISSING_SUBJECT_ID, name=MISSING_SUBJECT_NAME))

    horarios: tuple[Timetable, ...] = ()
    if colocaciones:
        horarios = (
            Timetable(
                id=UNTIS_TIMETABLE_ID,
                name=UNTIS_TIMETABLE_NAME,
                assignments=colocaciones,
            ),
        )

    return UntisProject(
        school=_read_school(r, root),
        time_grids=_read_time_grids(r, root),
        departments=_read_departments(r, root),
        classes=_read_classes(r, root),
        teachers=_read_teachers(r, root),
        rooms=_read_rooms(r, root),
        subjects=materias,
        student_groups=_read_student_groups(r, root),
        lessons=lecciones,
        timetables=horarios,
        date_schemes=_read_date_schemes(r, root),
    )


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #


def _child(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    nodo = ET.SubElement(parent, tag)
    if text is not None:
        nodo.text = text
    return nodo


def _opt_text(parent: ET.Element, tag: str, text: str) -> None:
    """Añade `<tag>text</tag>` solo si hay texto."""
    if text:
        _child(parent, tag, text)


def _opt_ref(parent: ET.Element, tag: str, ids: str | Iterable[str] | None, prefix: str) -> None:
    """Añade `<tag id="..."/>` con los ids prefijados (separados por espacios)."""
    if ids is None:
        return
    lista = [ids] if isinstance(ids, str) else list(ids)
    valor = " ".join(add_prefix(i, prefix) for i in lista if i)
    if valor:
        ET.SubElement(parent, tag, {"id": valor})


def _entity(parent: ET.Element, tag: str, ident: str, prefix: str) -> ET.Element:
    """Elemento de datos maestros con su id prefijado."""
    return ET.SubElement(parent, tag, {"id": add_prefix(ident, prefix)})


def _write_general(root: ET.Element, school: SchoolInfo) -> None:
    general = _child(root, "general")
    for tag, valor in (
        ("schoolname", school.name),
        ("schooltype", school.school_type),
        ("schoolyearbegindate", school.school_year_begin),
        ("schoolyearenddate", school.school_year_end),
        ("header1", school.header1),
        ("header2", school.header2),
        ("footer", school.footer),
        ("termname", school.term_name),
        ("termbegindate", school.term_begin),
        ("termenddate", school.term_end),
    ):
        _child(general, tag, valor or None)


def _write_time_grids(root: ET.Element, grids: tuple[TimeGrid, ...]) -> None:
    nodo = _child(root, "timeperiods")
    contador = 0
    for grid in grids:
        for dia in sorted(grid.days):
            for p in sorted(grid.periods, key=lambda p: p.number):
                contador += 1
                tp = ET.SubElement(nodo, "timeperiod", {"id": f"TP_{contador}"})
                _child(tp, "day", str(dia))
                _child(tp, "period", str(p.number))
                _child(tp, "starttime", minutes_to_hhmm(p.start))
                _child(tp, "endtime", minutes_to_hhmm(p.end))
                _child(tp, "timegrid", grid.id)


def _write_master_data(root: ET.Element, project: UntisProject) -> None:
    """Datos maestros en el orden del export de Untis (con sus secciones vacías)."""
    _child(root, "holidays")
    _child(root, "descriptions")

    nodo = _child(root, "departments")
    for d in project.departments:
        e = _entity(nodo, "department", d.id, DEPARTMENT_PREFIX)
        _opt_text(e, "longname", d.name)

    nodo = _child(root, "rooms")
    for a in project.rooms:
        e = _entity(nodo, "room", a.id, ROOM_PREFIX)
        _opt_text(e, "longname", a.name)
        _opt_text(e, "text", a.text)
        _opt_ref(e, "room_department", a.department, DEPARTMENT_PREFIX)

    nodo = _child(root, "subjects")
    for s in project.subjects:
        if s.id == MISSING_SUBJECT_ID:
            continue
        e = _entity(nodo, "subject", s.id, SUBJECT_PREFIX)
        _opt_text(e, "longname", s.name)
        _opt_text(e, "forecolor", s.fore_color)
        _opt_text(e, "backcolor", s.back_color)

    nodo = _child(root, "teachers")
    for t in project.teachers:
        e = _entity(nodo, "teacher", t.id, TEACHER_PREFIX)
        _opt_text(e, "forename", t.forename)
        _opt_text(e, "surname", t.surname)
        _opt_text(e, "gender", t.gender)
        _opt_text(e, "status", t.status)
        _opt_text(e, "payrollnumber", t.payroll_number)
        _opt_text(e, "email", t.email)
        _opt_text(e, "text", t.text)
        _opt_ref(e, "teacher_department", t.department, DEPARTMENT_PREFIX)

    nodo = _child(root, "classes")
    for c in project.classes:
        e = _entity(nodo, "class", c.id, CLASS_PREFIX)
        _opt_text(e, "longname", c.name)
        _opt_ref(e, "class_room", c.home_room, ROOM_PREFIX)
        _opt_text(e, "text", c.text)
        _opt_ref(e, "class_department", c.department, DEPARTMENT_PREFIX)
        _opt_text(e, "timegrid", c.time_grid)

    _child(root, "students")

    nodo = _child(root, "studentgroups")
    for g in project.student_groups:
        e = _entity(nodo, "studentgroup", g.id, STUDENT_GROUP_PREFIX)
        _opt_ref(e, "subject", g.subject, SUBJECT_PREFIX)
        clases = _child(e, "classes")
        for cid in g.classes:
            _entity(clases, "class", cid, CLASS_PREFIX)

    nodo = _child(root, "lesson_date_schemes")
    for ds in project.date_schemes:
        e = _entity(nodo, "lesson_date_scheme", ds.id, DATE_SCHEME_PREFIX)
        _opt_text(e, "date_scheme", ds.pattern)
        _opt_text(e, "periodic_weeks", ds.periodic_weeks)


def _format_teacher_value(value: float) -> str:
    """`5.0` -> `"500000"`."""
    return str(round(value * TEACHER_VALUE_SCALE))


def _untis_timetable(project: UntisProject) -> Timetable | None:
    """Horario a exportar en `times`: el de Untis si existe; si no, el último."""
    return project.timetable_by_id(UNTIS_TIMETABLE_ID) or (
        project.timetables[-1] if project.timetables else None
    )


def _write_time(parent: ET.Element, a: Assignment, grid: TimeGrid | None) -> None:
    """Una colocación; las horas de reloj salen de la rejilla de la lección."""
    t = _child(parent, "time")
    _child(t, "assigned_day", str(a.day))
    _child(t, "assigned_period", str(a.period))
    periodo = grid.period(a.period) if grid is not None else None
    if periodo is not None:
        _child(t, "assigned_starttime", minutes_to_hhmm(periodo.start))
        _child(t, "assigned_endtime", minutes_to_hhmm(periodo.end))
    _opt_ref(t, "assigned_room", a.room, ROOM_PREFIX)


def _write_lessons(root: ET.Element, project: UntisProject) -> None:
    horario = _untis_timetable(project)
    por_linea: dict[tuple[int, int], list[Assignment]] = {}
    if horario is not None:
        for a in horario.assignments:
            por_linea.setdefault((a.lesson_number, a.line), []).append(a)
    rejillas = {g.id: g for g in project.time_grids}

    nodo = _child(root, "lessons")
    for le in project.lessons:
        grid = rejillas.get(le.time_grid)
        for i, ln in enumerate(le.lines):
            e = ET.SubElement(nodo, "lesson", {"id": build_lesson_id(le.number, i)})
            _child(e, "periods", str(le.periods_per_week))
            if ln.subject != MISSING_SUBJECT_ID:
                _opt_ref(e, "lesson_subject", ln.subject, SUBJECT_PREFIX)
            _opt_ref(e, "lesson_teacher", ln.teacher, TEACHER_PREFIX)
            _opt_ref(e, "lesson_classes", ln.classes, CLASS_PREFIX)
            _opt_text(e, "timegrid", le.time_grid)
            if ln.weekly_value:
                _child(e, "teacher_value", _format_teacher_value(ln.weekly_value))
            _opt_ref(e, "lesson_studentgroups", ln.student_group, STUDENT_GROUP_PREFIX)
            _opt_text(e, "effectivebegindate", le.effective_begin)
            _opt_text(e, "effectiveenddate", le.effective_end)
            if le.block:
                _child(e, "block", ",".join(str(b) for b in le.block))
            _opt_text(e, "occurence", le.occurrence)
            tiempos = _child(e, "times")
            for a in por_linea.get((le.number, i), ()):
                _write_time(tiempos, a, grid)


def write_xml(project: UntisProject, path: str | Path, *, now: datetime | None = None) -> None:
    """Escribe el proyecto como XmlInterface 3.x (UTF-8, con sangría).

    Solo se escribe lo que el modelo guarda; lo que XmlInterface no puede llevar
    (ponderación, deseos, mín./máx.) se ignora. De los horarios del proyecto se
    exporta uno: `id="untis"` si existe, o el último. Los ids llevan de nuevo el
    prefijo de su tipo. `now` fija el sello `date`/`time` del documento (por
    defecto, la hora local actual), como hace Untis en cada exportación.
    """
    momento = now or datetime.now()
    root = ET.Element(
        "document",
        {
            "xmlns": UNTIS_NS,
            "xmlns:xsi": XSI_NS,
            "version": XML_VERSION,
            "xsi:schemaLocation": XSD_LOCATION,
            "date": momento.strftime("%Y%m%d"),
            "time": momento.strftime("%H%M%S"),
        },
    )
    _write_general(root, project.school)
    _write_time_grids(root, project.time_grids)
    _write_master_data(root, project)
    _write_lessons(root, project)
    arbol = ET.ElementTree(root)
    ET.indent(arbol, space="  ")
    arbol.write(Path(path), encoding="utf-8", xml_declaration=True)
