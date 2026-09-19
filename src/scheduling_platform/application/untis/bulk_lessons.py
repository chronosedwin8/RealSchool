"""Carga masiva de lecciones: una tabla plana, una fila por línea de acople.

Las lecciones son lo que más se teclea (900 en un colegio real) y además son lo
más enredado de Untis, porque una lección puede tener varias líneas acopladas.
El formato evita inventar nada: es la misma tabla que la ventana Lecciones, con
una fila por línea, y el **número de lección hace de pegamento**.

Columnas (nombre técnico, etiqueta española y alemana; valen las tres, sin
distinguir mayúsculas, acentos, espacios ni guiones bajos)::

    Lección;Materia;Profesor;Clases;Grupo de alumnos;Aula;Aula alternativa;
    Valor semanal;Horas/semana;Dobles mín;Dobles máx;Bloque;Rejilla;Fijada;
    Ignorar;No el mismo día;Valor semanal (lección)

De `Horas/semana` en adelante son columnas de la lección; las anteriores, de la
línea. `Valor semanal` es el de la línea (que es donde Untis lo guarda) y
`Valor semanal (lección)` el de la lección entera.

Reglas:

- **Las filas con el mismo valor en `Lección` son un acople**, en el orden del
  archivo. El valor es una *clave de agrupación*: si es un número, es el número
  de lección (si existe se actualiza entera, si no se crea con ese número); si
  es texto (`L1`, `bloque-ib`) agrupa líneas de una lección nueva; si está
  vacío, cada fila es una lección nueva de una sola línea. Las lecciones nuevas
  se numeran solas con el siguiente número libre.
- `Clases` admite varias separadas por comas.
- Las columnas de la **lección** (de `Horas/semana` en adelante) se leen de la
  primera línea; si una línea siguiente trae un valor distinto, es un error de
  esa fila. Al exportar salen solo en la primera línea, como en la ventana.
- Se valida lo mismo que editando en la ventana Lecciones: la materia, el
  profesor, las clases, el grupo y las aulas tienen que existir; las horas por
  semana, ser mayores que cero; la rejilla, existir.
- **La unidad atómica es la lección**: si falla cualquiera de sus líneas, la
  lección entera se queda fuera (no se cuela un acople a medias). Todo lo que
  entra se aplica en un único paso de deshacer.
- Al actualizar se conservan los campos que esta tabla no lleva (período,
  fechas de vigencia, secuencia de materias, grupo de lecciones): exportar,
  editar en Excel y volver a importar no pierde nada.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scheduling_platform.interop.tabular import Table, TableRow, read_table, write_table
from scheduling_platform.untis_model import Lesson, LessonLine, MinMax, UntisProject

from .bulk import (
    ImportReport,
    RowIssue,
    kind_labels,
    missing_message,
    missing_pairs,
    normalize,
    note_missing,
)
from .columns import ValueType, parse_value
from .session import UntisSession

#: Clave de esta cuadrícula en los informes (no es un `MasterKind`).
LESSON_KIND: Final = "lessons"

#: De dónde se importan las lecciones: una ruta, el texto del CSV o una tabla
#: ya troceada (`bulk.table_from_rows`, que es lo que usa el pegar de la UI).
type LessonSource = str | Path | Table


@dataclass(frozen=True, slots=True)
class LessonColumn:
    """Una columna del formato de lecciones."""

    field: str
    label: str
    label_de: str
    value_type: ValueType
    level: str
    """`"line"` (propia de la línea) o `"lesson"` (de la lección entera)."""
    reference: str | None = None
    """Colección del proyecto cuyos ids son los valores válidos."""
    aliases: tuple[str, ...] = ()
    """Otros nombres admitidos además del campo y las dos etiquetas."""

    def title(self, language: str = "es") -> str:
        return self.label_de if language == "de" else self.label


#: El formato, en el orden en que se exporta.
LESSON_COLUMNS: Final[tuple[LessonColumn, ...]] = (
    LessonColumn(
        "lesson", "Lección", "Unterricht", ValueType.TEXT, "key", aliases=("numero", "nr")
    ),
    LessonColumn("subject", "Materia", "Fach", ValueType.TEXT, "line", "subjects"),
    LessonColumn("teacher", "Profesor", "Lehrer", ValueType.OPT_TEXT, "line", "teachers"),
    LessonColumn("classes", "Clases", "Klassen", ValueType.LIST, "line", "classes"),
    LessonColumn(
        "student_group",
        "Grupo de alumnos",
        "Schülergruppe",
        ValueType.OPT_TEXT,
        "line",
        "student_groups",
        aliases=("grupo_alumnos", "grupo"),
    ),
    LessonColumn("room", "Aula", "Raum", ValueType.OPT_TEXT, "line", "rooms"),
    LessonColumn(
        "alternative_room", "Aula alternativa", "Ausweichraum", ValueType.OPT_TEXT, "line", "rooms"
    ),
    LessonColumn("weekly_value", "Valor semanal", "Wochenwert", ValueType.TEXT, "line"),
    LessonColumn(
        "periods_per_week",
        "Horas/semana",
        "Std./Woche",
        ValueType.INT,
        "lesson",
        aliases=("periodos_semana", "persem"),
    ),
    LessonColumn(
        "double_periods_min", "Dobles mín", "Doppelstunden min", ValueType.OPT_INT, "lesson"
    ),
    LessonColumn(
        "double_periods_max", "Dobles máx", "Doppelstunden max", ValueType.OPT_INT, "lesson"
    ),
    LessonColumn("block", "Bloque", "Block", ValueType.LIST, "lesson"),
    LessonColumn("time_grid", "Rejilla", "Zeitraster", ValueType.TEXT, "lesson", "time_grids"),
    LessonColumn("fixed", "Fijada", "Fixiert", ValueType.BOOL, "lesson"),
    LessonColumn("ignore", "Ignorar", "Ignorieren", ValueType.BOOL, "lesson"),
    LessonColumn(
        "not_same_day", "No el mismo día", "Nicht am selben Tag", ValueType.BOOL, "lesson"
    ),
    LessonColumn(
        "lesson_weekly_value",
        "Valor semanal (lección)",
        "Wochenwert (Unterricht)",
        ValueType.TEXT,
        "lesson",
    ),
)

#: Campos del formato, en orden (encabezado de un bloque pegado).
LESSON_FIELDS: Final[tuple[str, ...]] = tuple(c.field for c in LESSON_COLUMNS)


def lesson_column_map() -> dict[str, LessonColumn]:
    """Nombre normalizado -> columna (campo técnico, etiqueta es/de y alias)."""
    mapa: dict[str, LessonColumn] = {}
    for columna in LESSON_COLUMNS:
        nombres = (columna.field, columna.label, columna.label_de, *columna.aliases)
        for nombre in nombres:
            mapa.setdefault(normalize(nombre), columna)
    return mapa


# --------------------------------------------------------------------------- #
# Exportar
# --------------------------------------------------------------------------- #


def _cell(lesson: Lesson, line: LessonLine, first: bool, column: LessonColumn) -> str:
    """Texto de una celda; las columnas de la lección solo en su primera línea."""
    if column.level == "key":
        return str(lesson.number)  # también en las sub-filas: es el pegamento del acople
    if column.level == "line":
        valores = {
            "subject": line.subject,
            "teacher": line.teacher or "",
            "classes": ", ".join(line.classes),
            "student_group": line.student_group or "",
            "room": line.room or "",
            "alternative_room": line.alternative_room or "",
            "weekly_value": f"{line.weekly_value:g}" if line.weekly_value else "",
        }
        return valores[column.field]
    if not first:
        return ""
    if column.field == "periods_per_week":
        return str(lesson.periods_per_week)
    if column.field == "double_periods_min":
        return "" if lesson.double_periods.min is None else str(lesson.double_periods.min)
    if column.field == "double_periods_max":
        return "" if lesson.double_periods.max is None else str(lesson.double_periods.max)
    if column.field == "block":
        return ",".join(str(b) for b in lesson.block)
    if column.field == "time_grid":
        return lesson.time_grid
    if column.field == "lesson_weekly_value":
        return f"{lesson.weekly_value:g}" if lesson.weekly_value else ""
    return "x" if getattr(lesson, column.field) else ""


def lesson_rows(
    session: UntisSession, numbers: Sequence[int] | None = None
) -> tuple[tuple[str, ...], ...]:
    """Filas del formato (sin encabezado) de esas lecciones, o de todas.

    Es lo que copia al portapapeles la ventana Lecciones: el mismo formato que
    se importa, así que lo copiado se puede volver a pegar tal cual.
    """
    elegidas = None if numbers is None else set(numbers)
    return tuple(
        tuple(_cell(le, linea, i == 0, c) for c in LESSON_COLUMNS)
        for le in session.project.lessons
        if elegidas is None or le.number in elegidas
        for i, linea in enumerate(le.lines)
    )


def export_lessons(session: UntisSession, *, language: str = "es", delimiter: str = ";") -> str:
    """CSV de todas las lecciones: una fila por línea de acople."""
    return write_table(
        tuple(c.title(language) for c in LESSON_COLUMNS),
        lesson_rows(session),
        delimiter=delimiter,
    )


# --------------------------------------------------------------------------- #
# Importar
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Group:
    """Las filas de una misma lección, en el orden del archivo."""

    key: str
    rows: tuple[TableRow, ...]


def _headers(
    headers: tuple[str, ...], issues: list[RowIssue]
) -> tuple[dict[str, LessonColumn], tuple[str, ...]]:
    mapa = lesson_column_map()
    reconocidas: dict[str, LessonColumn] = {}
    desconocidas: list[str] = []
    for encabezado in headers:
        columna = mapa.get(normalize(encabezado))
        if columna is None:
            desconocidas.append(encabezado)
            issues.append(RowIssue(0, encabezado, "", f"Columna desconocida: {encabezado!r}"))
        else:
            reconocidas[encabezado] = columna
    return reconocidas, tuple(desconocidas)


def _group_rows(tabla: Table, clave: str | None) -> list[_Group]:
    """Agrupa las filas por el valor de la columna Lección (vacío = una cada una)."""
    orden: list[str] = []
    grupos: dict[str, list[TableRow]] = {}
    for fila in tabla.rows:
        texto = fila.get(clave).strip() if clave else ""
        etiqueta = texto or f"\x00nueva{fila.number}"
        if etiqueta not in grupos:
            orden.append(etiqueta)
            grupos[etiqueta] = []
        grupos[etiqueta].append(fila)
    return [_Group("" if e.startswith("\x00") else e, tuple(grupos[e])) for e in orden]


def _parse(
    columna: LessonColumn,
    texto: str,
    fila: TableRow,
    clave: str,
    issues: list[RowIssue],
    nombre: str,
) -> tuple[bool, object]:
    """`(vale, valor)` de una celda; si no vale, el motivo queda apuntado.

    El valor bueno puede ser `None` (una columna opcional vacía), así que el
    "vale" va aparte: confundirlos se comería filas enteras sin decir por qué.
    """
    try:
        valor = parse_value(texto, columna.value_type)
        if columna.field == "block":
            return True, (tuple(int(x) for x in valor) if isinstance(valor, tuple) else ())
        if columna.field in ("weekly_value", "lesson_weekly_value"):
            return True, (float(texto.replace(",", ".")) if texto.strip() else 0.0)
    except ValueError as exc:
        issues.append(RowIssue(fila.number, nombre, clave, str(exc), columna.field))
        return False, None
    return True, valor


def _check_refs(
    project: UntisProject,
    columna: LessonColumn,
    valor: object,
    fila: TableRow,
    clave: str,
    issues: list[RowIssue],
    nombre: str,
    perdidos: dict[str, list[str]],
) -> bool:
    """`True` si la referencia existe; si no, apunta qué falta y qué hacer antes."""
    if columna.reference is None or valor in (None, "", ()):
        return True
    validos = {e.id for e in getattr(project, columna.reference)}
    faltan = [v for v in (valor if isinstance(valor, tuple) else (valor,)) if str(v) not in validos]
    for falta in faltan:
        note_missing(perdidos, columna.reference, falta)
        issues.append(
            RowIssue(
                fila.number,
                nombre,
                clave,
                missing_message(columna.reference, falta),
                columna.field,
            )
        )
    return not faltan


def _line_of(
    project: UntisProject,
    fila: TableRow,
    campos: dict[str, LessonColumn],
    clave: str,
    issues: list[RowIssue],
    perdidos: dict[str, list[str]],
) -> LessonLine | None:
    """Una línea del acople a partir de una fila; `None` si algo no vale."""
    valores: dict[str, object] = {}
    correcta = True
    for nombre, columna in campos.items():
        if columna.level != "line":
            continue
        vale, valor = _parse(columna, fila.get(nombre), fila, clave, issues, nombre)
        if not vale:
            correcta = False
            continue
        if not _check_refs(project, columna, valor, fila, clave, issues, nombre, perdidos):
            correcta = False
            continue
        valores[columna.field] = valor
    if not valores.get("subject"):
        issues.append(RowIssue(fila.number, "", clave, "La línea necesita materia", "subject"))
        correcta = False
    if not correcta:
        return None
    try:
        return LessonLine(
            subject=str(valores.get("subject", "")),
            teacher=_opt(valores.get("teacher")),
            classes=_tuple(valores.get("classes")),
            student_group=_opt(valores.get("student_group")),
            room=_opt(valores.get("room")),
            alternative_room=_opt(valores.get("alternative_room")),
            weekly_value=_float(valores.get("weekly_value")),
        )
    except (ValueError, TypeError) as exc:
        issues.append(RowIssue(fila.number, "", clave, str(exc)))
        return None


def _opt(valor: object) -> str | None:
    return str(valor) if valor not in (None, "") else None


def _float(valor: object) -> float:
    return float(valor) if isinstance(valor, int | float) else 0.0


def _tuple(valor: object) -> tuple[str, ...]:
    return tuple(str(v) for v in valor) if isinstance(valor, tuple) else ()


def _lesson_values(
    project: UntisProject,
    grupo: _Group,
    campos: dict[str, LessonColumn],
    issues: list[RowIssue],
    perdidos: dict[str, list[str]],
) -> dict[str, object] | None:
    """Columnas de la lección: se leen de la primera línea y las demás deben repetirlas."""
    valores: dict[str, object] = {}
    correcta = True
    for nombre, columna in campos.items():
        if columna.level != "lesson":
            continue
        vale, primera = _parse(
            columna, grupo.rows[0].get(nombre), grupo.rows[0], grupo.key, issues, nombre
        )
        if not vale:
            correcta = False
            continue
        if not _check_refs(
            project, columna, primera, grupo.rows[0], grupo.key, issues, nombre, perdidos
        ):
            correcta = False
            continue
        valores[columna.field] = primera
        for fila in grupo.rows[1:]:
            texto = fila.get(nombre)
            if not texto.strip():
                continue
            repite, repetido = _parse(columna, texto, fila, grupo.key, issues, nombre)
            if not repite:
                correcta = False
                continue
            if repetido != primera:
                issues.append(
                    RowIssue(
                        fila.number,
                        nombre,
                        grupo.key,
                        f"Las líneas de una lección comparten esta columna: aquí pone "
                        f"{texto!r} y en la primera línea {_as_text(primera)!r}",
                        columna.field,
                    )
                )
                correcta = False
    return valores if correcta else None


def _as_text(valor: object) -> str:
    if isinstance(valor, tuple):
        return ",".join(str(v) for v in valor)
    return "" if valor is None else str(valor)


def _default_grid(project: UntisProject, lines: Sequence[LessonLine]) -> str:
    """Rejilla de la primera clase, como hace `add_lesson`; si no, la primera."""
    for linea in lines:
        for clase in linea.classes:
            entidad = project.class_by_id.get(clase)
            if entidad is not None and entidad.time_grid:
                return entidad.time_grid
    return project.time_grids[0].id if project.time_grids else ""


def _build_lesson(
    project: UntisProject,
    numero: int,
    lines: tuple[LessonLine, ...],
    valores: dict[str, object],
    previa: Lesson | None,
) -> Lesson:
    """Lección nueva o actualizada; una actualización conserva lo que la tabla no trae."""
    dobles = MinMax(
        _int_or_none(valores.get("double_periods_min")),
        _int_or_none(valores.get("double_periods_max")),
    )
    base = previa if previa is not None else None
    campos: dict[str, object] = {
        "lines": lines,
        "periods_per_week": _horas(valores),
        "double_periods": dobles,
        "block": valores.get("block", ()),
        "fixed": bool(valores.get("fixed", False)),
        "ignore": bool(valores.get("ignore", False)),
        "not_same_day": bool(valores.get("not_same_day", False)),
        "weekly_value": _float(valores.get("lesson_weekly_value")),
        "time_grid": str(valores.get("time_grid") or "") or _default_grid(project, lines),
    }
    if base is None:
        return Lesson(number=numero, **campos)  # type: ignore[arg-type]
    return dataclasses.replace(base, **campos)  # type: ignore[arg-type]


def _horas(valores: dict[str, object]) -> int:
    """Horas por semana de la lección (0 si la columna no venía)."""
    valor = valores.get("periods_per_week")
    return valor if isinstance(valor, int) else 0


def _int_or_none(valor: object) -> int | None:
    return int(valor) if isinstance(valor, int) else None


def _trim_assignments(project: UntisProject, recortadas: dict[int, int]) -> UntisProject:
    """Quita las colocaciones de líneas que ya no existen tras actualizar una lección."""
    if not recortadas:
        return project
    horarios = tuple(
        dataclasses.replace(
            tt,
            assignments=tuple(
                a for a in tt.assignments if a.line < recortadas.get(a.lesson_number, a.line + 1)
            ),
        )
        for tt in project.timetables
    )
    return dataclasses.replace(project, timetables=horarios)


@dataclass(frozen=True, slots=True)
class _Plan:
    lessons: tuple[Lesson, ...]
    trimmed: dict[int, int]
    report: ImportReport
    changed: bool


def _build_plan(session: UntisSession, source: LessonSource, delimiter: str | None) -> _Plan:
    """Calcula las lecciones resultantes y el informe sin tocar la sesión."""
    tabla = source if isinstance(source, Table) else read_table(source, delimiter=delimiter)
    issues = [RowIssue(e.row, e.column, "", e.message) for e in tabla.errors]
    p = session.project
    actuales = list(p.lessons)
    if not tabla.headers:
        return _Plan(tuple(actuales), {}, ImportReport(LESSON_KIND, issues=tuple(issues)), False)
    campos, desconocidas = _headers(tabla.headers, issues)
    if not any(c.level == "line" and c.field == "subject" for c in campos.values()):
        issues.append(RowIssue(0, "", "", "Falta la columna de la materia («Materia»)"))
        return _Plan(
            tuple(actuales),
            {},
            ImportReport(LESSON_KIND, issues=tuple(issues), unknown_columns=desconocidas),
            False,
        )
    columna_clave = next((h for h, c in campos.items() if c.level == "key"), None)
    posicion = {le.number: i for i, le in enumerate(actuales)}
    siguiente = max((le.number for le in actuales), default=0) + 1
    creadas: list[str] = []
    actualizadas: list[str] = []
    iguales: list[str] = []
    cambios: dict[int, Lesson] = {}
    altas: list[Lesson] = []
    recortadas: dict[int, int] = {}
    usados: set[int] = set()
    perdidos: dict[str, list[str]] = {}
    for grupo in _group_rows(tabla, columna_clave):
        antes = len(issues)
        lineas = [_line_of(p, f, campos, grupo.key, issues, perdidos) for f in grupo.rows]
        valores = _lesson_values(p, grupo, campos, issues, perdidos)
        if valores is not None and _horas(valores) <= 0:
            issues.append(
                RowIssue(
                    grupo.rows[0].number,
                    "Horas/semana",
                    grupo.key,
                    "Las horas por semana tienen que ser mayores que cero",
                    "periods_per_week",
                )
            )
        numero, error = _number_of(grupo, posicion, usados, siguiente)
        if error:
            issues.append(RowIssue(grupo.rows[0].number, "Lección", grupo.key, error, "lesson"))
        if len(issues) != antes or valores is None or any(x is None for x in lineas):
            continue
        previa = actuales[posicion[numero]] if numero in posicion else None
        try:
            nueva = _build_lesson(
                p, numero, tuple(x for x in lineas if x is not None), valores, previa
            )
        except (ValueError, TypeError) as exc:
            issues.append(RowIssue(grupo.rows[0].number, "", grupo.key, str(exc)))
            continue
        usados.add(numero)
        if previa is None:
            altas.append(nueva)
            creadas.append(str(numero))
            siguiente = max(siguiente, numero + 1)
        elif nueva == previa:
            iguales.append(str(numero))
        else:
            cambios[posicion[numero]] = nueva
            actualizadas.append(str(numero))
            if len(nueva.lines) < len(previa.lines):
                recortadas[numero] = len(nueva.lines)
    resultantes = list(actuales)
    for indice, leccion in cambios.items():
        resultantes[indice] = leccion
    resultantes.extend(altas)
    informe = ImportReport(
        kind=LESSON_KIND,
        created=tuple(creadas),
        updated=tuple(actualizadas),
        unchanged=tuple(iguales),
        issues=tuple(issues),
        unknown_columns=desconocidas,
        missing=missing_pairs(perdidos),
    )
    return _Plan(tuple(resultantes), recortadas, informe, bool(altas or cambios))


def _number_of(
    grupo: _Group, posicion: dict[int, int], usados: set[int], siguiente: int
) -> tuple[int, str]:
    """Número de la lección del grupo y el motivo si la clave no vale."""
    if not grupo.key:
        return siguiente, ""
    if grupo.key.isdigit():
        numero = int(grupo.key)
        if numero in usados:
            return numero, (
                f"El número {numero} ya se lo ha llevado otra lección de este archivo; "
                "ponle otro o deja la casilla vacía"
            )
        return numero, ""
    if grupo.key.lstrip("-").isdigit():
        return siguiente, f"Número de lección no válido: {grupo.key!r}"
    return siguiente, ""  # clave de texto: agrupa líneas de una lección nueva


# --------------------------------------------------------------------------- #
# Casos de uso
# --------------------------------------------------------------------------- #


def preview_lessons(
    session: UntisSession, source: LessonSource, *, delimiter: str | None = None
) -> ImportReport:
    """Qué lecciones se crearían y cuáles se actualizarían. No toca nada."""
    return _build_plan(session, source, delimiter).report


def import_lessons(
    session: UntisSession,
    source: LessonSource,
    *,
    strict: bool = False,
    delimiter: str | None = None,
) -> ImportReport:
    """Crea y actualiza lecciones desde la tabla, en un solo paso de deshacer."""
    plan = _build_plan(session, source, delimiter)
    if not plan.changed or (strict and plan.report.issues):
        return plan.report
    proyecto = dataclasses.replace(session.project, lessons=plan.lessons)
    proyecto = _trim_assignments(proyecto, plan.trimmed)
    cuantas = len(plan.report.created) + len(plan.report.updated)
    singular, plural = kind_labels(LESSON_KIND)
    session.apply(proyecto, f"Importar {cuantas} {plural if cuantas != 1 else singular}")
    return dataclasses.replace(plan.report, applied=True)


class BulkLessonsMixin:
    """Carga masiva de lecciones, para heredar en `UntisService`."""

    def preview_lessons(
        self, session: UntisSession, source: LessonSource, *, delimiter: str | None = None
    ) -> ImportReport:
        """Qué lecciones se crearían y cuáles se actualizarían, sin tocar nada."""
        return preview_lessons(session, source, delimiter=delimiter)

    def import_lessons(
        self,
        session: UntisSession,
        source: LessonSource,
        *,
        strict: bool = False,
        delimiter: str | None = None,
    ) -> ImportReport:
        """Crea y actualiza lecciones en un solo paso de deshacer."""
        return import_lessons(session, source, strict=strict, delimiter=delimiter)

    def export_lessons(
        self, session: UntisSession, *, language: str = "es", delimiter: str = ";"
    ) -> str:
        """CSV de todas las lecciones, una fila por línea de acople."""
        return export_lessons(session, language=language, delimiter=delimiter)
