"""Lectura y escritura de los archivos GPU (DIF de texto) de Untis.

Cada archivo `GPUnnn.TXT` es una tabla: un registro por línea, campos separados
por coma, textos entre comillas dobles (`""` escapa una comilla) y fin de línea
CRLF. Untis 2022 exige Windows-1252 al importar, así que es la codificación de
escritura por defecto.

Lectura tolerante (sección 9 de `REFACTOR_UNTIS_MAESTRO.md`):

- Codificación: BOM → `utf-8-sig` (o UTF-16); si no, UTF-8 estricto; si falla,
  Windows-1252. El BOM ya rompió MiUntisWeb en producción.
- Separador: se detecta entre `,`, `;` y tabulador (Untis deja elegirlo al
  exportar); la escritura siempre usa coma.
- Columnas: una fila corta se completa con vacíos y las columnas de más se
  ignoran; nunca se aborta por una fila mal formada.

Archivos cubiertos: `GPU001` horario (el que consume MiUntisWeb), `GPU002`
lecciones, `GPU003`-`GPU007` datos maestros y `GPU016` deseos de tiempo. El
orden de columnas de cada uno está en las tablas `GPU0nn_COLUMNS` de abajo,
tomado del manual de Untis ("Technische Information > Allgemeine
Schnittstellen", https://www.untis.at/manual/hid_export.htm) y contrastado con
la librería Enbrea.Untis.Gpu (https://github.com/enbrea/enbrea.untis.gpu).

Acoples en `GPU002`: Untis escribe una fila por (línea del acople, clase). Todas
las filas de una lección comparten número; al leer se reagrupan en una única
`Lesson` con sus `LessonLine` en orden de aparición (ver `_group_lines`).
"""

from __future__ import annotations

import codecs
import csv
import io
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Final

from scheduling_platform.untis_model import (
    LINES_PER_LESSON,
    REQUEST_MAX,
    REQUEST_MIN,
    UNSET,
    Assignment,
    Department,
    EntityKind,
    Lesson,
    LessonLine,
    MinMax,
    Room,
    SchoolClass,
    SchoolInfo,
    Subject,
    Teacher,
    TimeRequest,
    Timetable,
    UntisProject,
)

# --------------------------------------------------------------------------- #
# Disposición de columnas (orden oficial del manual de Untis, índice 0).
#
# Los nombres son internos; solo importa la posición. `write_width` es cuántas
# columnas se escriben: la anchura documentada, salvo GPU001, que replica la
# forma clásica de 9 campos (7 datos + duración + texto de línea vacíos) que
# producen Untis y los ejemplos de Enbrea y que consume MiUntisWeb.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class GpuLayout:
    """Orden de columnas de un archivo GPU."""

    filename: str
    columns: tuple[str, ...]
    write_width: int
    index: dict[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "index", {n: i for i, n in enumerate(self.columns)})
        if len(self.index) != len(self.columns):
            raise ValueError(f"{self.filename}: columnas repetidas")


#: GPU001.TXT Stundenplan. Fuente: manual Untis (hid_export_stp) + Enbrea
#: `GpuLessonTime` (índices 0-7 idénticos). Una fila por (línea, clase, día, período).
GPU001_COLUMNS: Final = GpuLayout(
    "GPU001.TXT",
    (
        "lesson_number",  # 1  Unterr.-Nr.  Num
        "class",  # 2  Klasse
        "teacher",  # 3  Lehrer
        "subject",  # 4  Fach
        "room",  # 5  Raum
        "day",  # 6  Tag  Num
        "period",  # 7  Stunde  Num
        "duration",  # 8  Stundenlänge (hh:mm, solo rejilla por minutos)
        "line_text_1",  # 9  Zeilentext 1
        "line_text_2",  # 10 Zeilentext 2
        "webuntis_from",  # 11 WebUntis Zeit Von
        "webuntis_to",  # 12 WebUntis Zeit Bis
        "oasis_alias",  # 13
        "oasis_subject_group",  # 14
        "oasis_period_name",  # 15
        "pedav_lesson_group",  # 16
    ),
    write_width=9,
)

#: GPU002.TXT Unterricht. Fuente: manual Untis (hid_export_unt) + Enbrea `GpuLesson`.
GPU002_COLUMNS: Final = GpuLayout(
    "GPU002.TXT",
    (
        "lesson_number",  # 1  Unt-Nummer  Num
        "periods_per_week",  # 2  Wochenstunden  Num
        "class_periods",  # 3  Wochenstd. Kla. (solo en la 1a fila de cada clase)
        "teacher_periods",  # 4  Wochenstd. Le. (solo en la 1a fila de cada profesor)
        "class",  # 5  Klasse
        "teacher",  # 6  Lehrer
        "subject",  # 7  Fach
        "room",  # 8  Fachraum (Enbrea: lista separada por "~")
        "statistics",  # 9  Statistik 1 Unt.
        "students",  # 10 Studentenzahl
        "weekly_value",  # 11 Wochenwert (del profesor de esta fila)
        "group",  # 12 Gruppe
        "line_text_1",  # 13 Zeilentext 1
        "line_value",  # 14 Zeilenwert
        "date_from",  # 15 Datum von
        "date_to",  # 16 Datum bis
        "year_value",  # 17 Jahreswert
        "text",  # 18 Text
        "split_number",  # 19 Teilungs-Nummer
        "home_room",  # 20 Stammraum
        "description",  # 21 Beschreibung
        "fg_color",  # 22 Farbe Vg.
        "bg_color",  # 23 Farbe Hg.
        "flags",  # 24 Kennzeichen (X = fijada, i = ignorar)
        "class_subject_sequence",  # 25 Fachfolge Klassen
        "teacher_subject_sequence",  # 26 Fachfolge Lehrer
        "class_collision_flag",  # 27 Klassen-Kollisions-Kennz.
        "double_min",  # 28 Doppelstd. min.
        "double_max",  # 29 Doppelstd. max.
        "block_size",  # 30 Blockgröße
        "periods_in_room",  # 31 Std. im Raum
        "priority",  # 32 Priorität
        "teacher_statistics",  # 33 Statistik 1 Lehrer
        "students_male",  # 34
        "students_female",  # 35
        "value_factor",  # 36 Wert bzw. Faktor
        "block_2",  # 37 2. Block
        "block_3",  # 38 3. Block
        "line_text_2",  # 39 Zeilentext-2
        "own_value",  # 40 Eigenwert
        "own_value_scaled",  # 41 Eigenwert (1/100000)
        "student_group",  # 42 Schülergruppe
        "periodic_hours",  # 43 Wochenstunden Jahres-Perioden-Planung
        "year_hours",  # 44 Jahresstunden
        "line_lesson_group",  # 45 Zeilen-Unterrichtsgruppe
        "students_inter",  # 46 Studenten intergeschlechtlich
    ),
    write_width=46,
)

#: GPU003.TXT Klassen. Fuente: manual Untis (hid_export_kla) + Enbrea `GpuClass`.
GPU003_COLUMNS: Final = GpuLayout(
    "GPU003.TXT",
    (
        "id",  # 1  Name
        "name",  # 2  Langname
        "statistics",  # 3
        "home_room",  # 4  Raum
        "flags",  # 5  Kennzeichen
        "free",  # 6
        "periods_per_day_min",  # 7  Min-Std./Tag
        "periods_per_day_max",  # 8  Max-Std./Tag
        "lunch_min",  # 9  Min-Mittagsp.
        "lunch_max",  # 10 Max-Mittagsp.
        "main_subjects_consecutive",  # 11 Hauptf.Folge ("max. Hauptfach-Folge")
        "main_subjects_per_day",  # 12 Hauptf.hint. (INCIERTO, ver informe)
        "class_group",  # 13 Kla-Gruppe
        "level",  # 14 Schul-Stufe
        "department",  # 15 Abteilung
        "factor",  # 16 Faktor
        "students_female",  # 17
        "students_male",  # 18
        "school_form",  # 19
        "date_from",  # 20
        "date_to",  # 21
        "special_text",  # 22
        "description",  # 23
        "fg_color",  # 24
        "bg_color",  # 25
        "statistics_2",  # 26
        "previous_name",  # 27
        "factor_export",  # 28
        "alias",  # 29
        "class_teacher",  # 30
        "main_class",  # 31
        "students_inter",  # 32
    ),
    write_width=32,
)

#: GPU004.TXT Lehrer. Fuente: manual Untis (hid_export_le) + Enbrea `GpuTeacher`.
GPU004_COLUMNS: Final = GpuLayout(
    "GPU004.TXT",
    (
        "id",  # 1  Name
        "surname",  # 2  Langname (apellido)
        "statistics",  # 3
        "personnel_number",  # 4
        "home_room",  # 5  Stammraum
        "flags",  # 6
        "free",  # 7
        "periods_per_day_min",  # 8  Std./Tag min.
        "periods_per_day_max",  # 9  Std./Tag max.
        "ntp_min",  # 10 Hohlstd. min. (semanal, INCIERTO)
        "ntp_max",  # 11 Hohlstd. max.
        "lunch_min",  # 12 Mittagsp. min.
        "lunch_max",  # 13 Mittagsp. max.
        "consecutive_max",  # 14 Std.-Folge max.
        "weekly_target",  # 15 Wochen-Soll
        "weekly_value",  # 16 Wochen-Wert
        "department",  # 17 Abteilung 1
        "value_factor",  # 18
        "department_2",  # 19
        "department_3",  # 20
        "status",  # 21
        "year_target",  # 22
        "text",  # 23
        "description",  # 24
        "fg_color",  # 25
        "bg_color",  # 26
        "statistics_2",  # 27
        "computed_factor",  # 28
        "forename",  # 29 Vorname
        "title",  # 30
        "gender",  # 31
        "home_school",  # 32
        "email",  # 33 E-Mail Adresse
        "block_note",  # 34
        "weekly_target_max",  # 35
        "alias",  # 36
        "personnel_number_2",  # 37
        "hourly_rate",  # 38
        "phone",  # 39
        "mobile",  # 40
        "birth_date",  # 41
        "external_name",  # 42
        "text_2",  # 43
        "entry_date",  # 44
        "exit_date",  # 45
    ),
    write_width=45,
)

#: GPU005.TXT Räume. Fuente: manual Untis (hid_export_raum) + Enbrea `GpuRoom`.
GPU005_COLUMNS: Final = GpuLayout(
    "GPU005.TXT",
    (
        "id",  # 1  Name
        "name",  # 2  Langname
        "alternative_room",  # 3  Ausweichraum
        "flags",  # 4
        "free",  # 5
        "dislocation",  # 6
        "room_weight",  # 7  Raum-Gewicht
        "capacity",  # 8  Kapazität
        "department",  # 9  Abteilung
        "corridor_1",  # 10
        "corridor_2",  # 11
        "special_text",  # 12
        "description",  # 13
        "fg_color",  # 14
        "bg_color",  # 15
        "statistics_1",  # 16
        "statistics_2",  # 17
    ),
    write_width=17,
)

#: GPU006.TXT Fächer. Fuente: manual Untis (hid_export_fa) + Enbrea `GpuSubject`.
GPU006_COLUMNS: Final = GpuLayout(
    "GPU006.TXT",
    (
        "id",  # 1  Name
        "name",  # 2  Langname
        "statistics",  # 3
        "required_room",  # 4  Raum
        "flags",  # 5  Kennzeichen (H = principal, D = dobles obligatorios)
        "free",  # 6
        "weekly_min",  # 7
        "weekly_max",  # 8
        "afternoon_min",  # 9
        "afternoon_max",  # 10
        "class_sequence",  # 11
        "teacher_sequence",  # 12
        "subject_group",  # 13 Fach-Gruppe
        "factor",  # 14
        "factor_num",  # 15
        "text",  # 16
        "description",  # 17
        "fg_color",  # 18
        "bg_color",  # 19
        "statistics_2",  # 20
        "alias",  # 21
    ),
    write_width=21,
)

#: GPU007.TXT Abteilungen. Fuente: manual Untis (hid_export_abt) + Enbrea `GpuDepartment`.
GPU007_COLUMNS: Final = GpuLayout("GPU007.TXT", ("id", "name"), write_width=2)

#: GPU016.TXT Zeitwünsche. Fuente: manual Untis (hid_export_zeitwunsch); Enbrea
#: no lo implementa. Una fila por (elemento, día, período, valor -3..+3).
GPU016_COLUMNS: Final = GpuLayout(
    "GPU016.TXT",
    (
        "kind",  # 1  Art des Elements (L, K, R, F)
        "entity_id",  # 2  Kurzname
        "day",  # 3  Tag
        "period",  # 4  Stunde
        "value",  # 5  Zeitwunsch (-3 bis 3)
    ),
    write_width=5,
)

#: Todas las disposiciones, por nombre de archivo.
GPU_LAYOUTS: Final[dict[str, GpuLayout]] = {
    layout.filename: layout
    for layout in (
        GPU001_COLUMNS,
        GPU002_COLUMNS,
        GPU003_COLUMNS,
        GPU004_COLUMNS,
        GPU005_COLUMNS,
        GPU006_COLUMNS,
        GPU007_COLUMNS,
        GPU016_COLUMNS,
    )
}

#: Letra de GPU016 por tipo de entidad (versión alemana de Untis).
REQUEST_KIND_CODES: Final[dict[EntityKind, str]] = {
    EntityKind.TEACHER: "L",
    EntityKind.CLASS: "K",
    EntityKind.ROOM: "R",
    EntityKind.SUBJECT: "F",
}
#: Letras aceptadas al leer; incluye las iniciales inglesas por tolerancia.
_REQUEST_KIND_BY_CODE: Final[dict[str, EntityKind]] = {
    "L": EntityKind.TEACHER,
    "T": EntityKind.TEACHER,
    "K": EntityKind.CLASS,
    "C": EntityKind.CLASS,
    "R": EntityKind.ROOM,
    "F": EntityKind.SUBJECT,
    "S": EntityKind.SUBJECT,
}

#: Kennzeichen de lección (GPU002) y de materia (GPU006) que el modelo entiende.
LESSON_FLAG_FIXED: Final = "X"
LESSON_FLAG_IGNORE: Final = "i"
SUBJECT_FLAG_MAIN: Final = "H"
SUBJECT_FLAG_DOUBLE: Final = "D"

#: Separador de listas dentro de un campo: solo el aula de GPU002, según Enbrea
#: (`GpuLesson.Rooms`). La clase NO se parte: Untis escribe una fila por clase.
LIST_SEPARATOR: Final = "~"
#: Id del horario que se crea al leer `GPU001`.
GPU_TIMETABLE_ID: Final = "GPU001"
#: Codificación de escritura por defecto (Untis 2022 la exige).
DEFAULT_ENCODING: Final = "cp1252"

_DELIMITERS: Final = (",", ";", "\t")
_QUOTED: Final = re.compile(r'"(?:[^"]|"")*"')

type Cell = str | int | Decimal | None
"""Valor de una celda al escribir: `str` va entre comillas, números y `None` no."""


# --------------------------------------------------------------------------- #
# Codificación y CSV
# --------------------------------------------------------------------------- #


#: Manejador de errores que imita a Windows con los 5 bytes que cp1252 no define
#: (0x81, 0x8D, 0x8F, 0x90, 0x9D): se leen y escriben tal cual (U+0081...).
#: Untis los escribe en sus propios archivos (visto en el export real
#: 2026-2027, dentro de nombres con tilde); sin esto, la exportación fallaría por un
#: nombre. Al escribir, cualquier otro carácter imposible se cambia por `?`.
UNTIS_ERRORS: Final = "untis-cp1252"


def _untis_errors(exc: UnicodeError) -> tuple[str | bytes, int]:
    if isinstance(exc, UnicodeDecodeError):
        crudo = exc.object[exc.start : exc.end]
        return "".join(chr(b) for b in crudo), exc.end
    if isinstance(exc, UnicodeEncodeError):
        trozo = exc.object[exc.start : exc.end]
        salida = bytes(ord(c) if 0x80 <= ord(c) <= 0x9F else ord("?") for c in trozo)
        return salida, exc.end
    raise exc


codecs.register_error(UNTIS_ERRORS, _untis_errors)


def decode_gpu(data: bytes) -> str:
    """Decodifica un archivo GPU con la política de lectura tolerante.

    BOM → la codificación que indique; si no hay BOM, UTF-8 estricto; si no es
    UTF-8 válido, Windows-1252 (sin errores: todo byte tiene lectura).
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors=UNTIS_ERRORS)


def sniff_delimiter(text: str) -> str:
    """Detecta el separador (`,`, `;` o tabulador) en la primera línea con datos.

    Cuenta las apariciones fuera de los textos entrecomillados; ante empate o
    ausencia gana la coma, que es el valor por defecto de Untis.
    """
    for linea in text.splitlines():
        if not linea.strip():
            continue
        sin_textos = _QUOTED.sub("", linea)
        cuentas = {d: sin_textos.count(d) for d in _DELIMITERS}
        mejor = max(_DELIMITERS, key=lambda d: cuentas[d])
        return mejor if cuentas[mejor] > 0 else ","
    return ","


@dataclass(frozen=True, slots=True)
class GpuRow:
    """Una fila leída, con acceso por nombre de columna tolerante a filas cortas."""

    layout: GpuLayout
    values: tuple[str, ...]

    def text(self, column: str) -> str:
        """Texto de la columna, sin espacios; vacío si la fila es más corta."""
        i = self.layout.index[column]
        return self.values[i].strip() if i < len(self.values) else ""

    def opt(self, column: str) -> str | None:
        """Texto de la columna o `None` si está vacía."""
        return self.text(column) or None

    def num(self, column: str) -> int | None:
        """Entero de la columna; `None` si está vacía o no es numérica."""
        return _parse_int(self.text(column))

    def real(self, column: str) -> float | None:
        """Real de la columna (admite coma decimal); `None` si no es numérico."""
        texto = self.text(column).replace(",", ".")
        if not texto:
            return None
        try:
            return float(texto)
        except ValueError:
            return None


def _parse_int(texto: str) -> int | None:
    if not texto:
        return None
    try:
        return int(texto)
    except ValueError:
        pass
    try:
        return int(float(texto.replace(",", ".")))
    except ValueError:
        return None


def parse_gpu(text: str, layout: GpuLayout) -> list[GpuRow]:
    """Parte el texto de un archivo GPU en filas; omite las filas vacías."""
    delimitador = sniff_delimiter(text)
    lector = csv.reader(io.StringIO(text, newline=""), delimiter=delimitador, strict=False)
    filas: list[GpuRow] = []
    for valores in lector:
        if not any(v.strip() for v in valores):
            continue
        filas.append(GpuRow(layout, tuple(valores)))
    return filas


def read_gpu_file(path: str | Path, layout: GpuLayout) -> list[GpuRow]:
    """Lee un archivo GPU con detección de codificación y separador."""
    return parse_gpu(decode_gpu(Path(path).read_bytes()), layout)


def render_gpu(rows: Iterable[Sequence[Cell]]) -> str:
    """Serializa filas al formato GPU: coma, textos entre comillas, CRLF.

    Los `str` vacíos se escriben como campo vacío sin comillas (como Untis);
    los números (`int`, `Decimal`) van sin comillas.
    """
    salida = io.StringIO(newline="")
    escritor = csv.writer(
        salida, delimiter=",", quotechar='"', quoting=csv.QUOTE_STRINGS, lineterminator="\r\n"
    )
    for fila in rows:
        escritor.writerow([None if v == "" else v for v in fila])
    return salida.getvalue()


def write_gpu_file(
    path: str | Path,
    rows: Iterable[Sequence[Cell]],
    *,
    encoding: str = DEFAULT_ENCODING,
    errors: str = UNTIS_ERRORS,
) -> Path:
    """Escribe filas en `path` con la codificación pedida (por defecto cp1252).

    Por defecto nunca falla por un carácter: ver `UNTIS_ERRORS`. Con
    `errors="strict"` se recupera el comportamiento estricto.
    """
    destino = Path(path)
    destino.write_bytes(render_gpu(rows).encode(encoding, errors=errors))
    return destino


class _RowBuilder:
    """Fila en blanco de una disposición, rellenable por nombre de columna."""

    def __init__(self, layout: GpuLayout) -> None:
        self._layout = layout
        self._cells: list[Cell] = [None] * layout.write_width

    def set(self, column: str, value: Cell) -> _RowBuilder:
        i = self._layout.index[column]
        if i >= self._layout.write_width:
            raise ValueError(f"{self._layout.filename}: {column!r} fuera de la anchura escrita")
        self._cells[i] = value
        return self

    @property
    def cells(self) -> list[Cell]:
        return self._cells


def _decimal(value: float) -> Decimal:
    """Número real con 5 decimales, como los escribe Untis (`2.00000`)."""
    return Decimal(f"{value:.5f}")


# --------------------------------------------------------------------------- #
# Datos maestros: GPU003-GPU007
# --------------------------------------------------------------------------- #


def _minmax(lo: int | None, hi: int | None) -> MinMax:
    """`MinMax` tolerante: valores negativos o incoherentes se descartan."""
    lo = lo if lo is not None and lo >= 0 else None
    hi = hi if hi is not None and hi >= 0 else None
    if lo is not None and hi is not None and lo > hi:
        return UNSET
    return MinMax(lo, hi) if lo is not None or hi is not None else UNSET


def _unique[T: (Department, SchoolClass, Teacher, Room, Subject)](
    items: Iterable[T],
) -> tuple[T, ...]:
    """Descarta ids repetidos (se queda con la primera aparición)."""
    vistos: dict[str, T] = {}
    for it in items:
        vistos.setdefault(it.id, it)
    return tuple(vistos.values())


def _department_rows(departments: Iterable[Department]) -> Iterator[list[Cell]]:
    for d in departments:
        yield _RowBuilder(GPU007_COLUMNS).set("id", d.id).set("name", d.name).cells


def _read_departments(rows: Iterable[GpuRow]) -> tuple[Department, ...]:
    return _unique(Department(id=r.text("id"), name=r.text("name")) for r in rows if r.text("id"))


def _class_rows(classes: Iterable[SchoolClass]) -> Iterator[list[Cell]]:
    for c in classes:
        yield (
            _RowBuilder(GPU003_COLUMNS)
            .set("id", c.id)
            .set("name", c.name)
            .set("home_room", c.home_room)
            .set("periods_per_day_min", c.periods_per_day.min)
            .set("periods_per_day_max", c.periods_per_day.max)
            .set("lunch_min", c.lunch_break.min)
            .set("lunch_max", c.lunch_break.max)
            .set("main_subjects_consecutive", c.main_subjects_consecutive)
            .set("main_subjects_per_day", c.main_subjects_per_day)
            .set("level", c.level)
            .set("department", c.department)
            .set("special_text", c.text)
            .cells
        )


def _read_classes(rows: Iterable[GpuRow]) -> tuple[SchoolClass, ...]:
    def una(r: GpuRow) -> SchoolClass:
        alumnos = sum(
            max(r.num(col) or 0, 0)
            for col in ("students_female", "students_male", "students_inter")
        )
        return SchoolClass(
            id=r.text("id"),
            name=r.text("name"),
            home_room=r.opt("home_room"),
            department=r.opt("department"),
            students=alumnos,
            level=r.num("level"),
            periods_per_day=_minmax(r.num("periods_per_day_min"), r.num("periods_per_day_max")),
            lunch_break=_minmax(r.num("lunch_min"), r.num("lunch_max")),
            main_subjects_per_day=r.num("main_subjects_per_day"),
            main_subjects_consecutive=r.num("main_subjects_consecutive"),
            text=r.text("special_text"),
        )

    return _unique(una(r) for r in rows if r.text("id"))


def _teacher_rows(teachers: Iterable[Teacher]) -> Iterator[list[Cell]]:
    for t in teachers:
        yield (
            _RowBuilder(GPU004_COLUMNS)
            .set("id", t.id)
            .set("surname", t.surname)
            .set("home_room", t.home_room)
            .set("periods_per_day_min", t.periods_per_day.min)
            .set("periods_per_day_max", t.periods_per_day.max)
            .set("ntp_min", t.ntp_per_week.min)
            .set("ntp_max", t.ntp_per_week.max)
            .set("lunch_min", t.lunch_break.min)
            .set("lunch_max", t.lunch_break.max)
            .set("consecutive_max", t.consecutive_max)
            .set("department", t.department)
            .set("forename", t.forename)
            .set("email", t.email)
            .set("personnel_number", t.payroll_number)
            .set("status", t.status)
            .set("text", t.text)
            .set("gender", t.gender)
            .cells
        )


def _read_teachers(rows: Iterable[GpuRow]) -> tuple[Teacher, ...]:
    def una(r: GpuRow) -> Teacher:
        seguidos = r.num("consecutive_max")
        return Teacher(
            id=r.text("id"),
            surname=r.text("surname"),
            forename=r.text("forename"),
            email=r.text("email"),
            department=r.opt("department"),
            home_room=r.opt("home_room"),
            periods_per_day=_minmax(r.num("periods_per_day_min"), r.num("periods_per_day_max")),
            ntp_per_week=_minmax(r.num("ntp_min"), r.num("ntp_max")),
            lunch_break=_minmax(r.num("lunch_min"), r.num("lunch_max")),
            consecutive_max=seguidos if seguidos is not None and seguidos >= 1 else None,
            text=r.text("text"),
            status=r.text("status"),
            payroll_number=r.text("personnel_number"),
            gender=r.text("gender"),
        )

    return _unique(una(r) for r in rows if r.text("id"))


def _room_rows(rooms: Iterable[Room]) -> Iterator[list[Cell]]:
    for a in rooms:
        yield (
            _RowBuilder(GPU005_COLUMNS)
            .set("id", a.id)
            .set("name", a.name)
            .set("alternative_room", a.alternative_room)
            .set("room_weight", a.room_weight)
            .set("capacity", a.capacity)
            .set("department", a.department)
            .set("special_text", a.text)
            .cells
        )


def _read_rooms(rows: Iterable[GpuRow]) -> tuple[Room, ...]:
    def una(r: GpuRow) -> Room:
        ident = r.text("id")
        alternativa = r.opt("alternative_room")
        capacidad = r.num("capacity")
        return Room(
            id=ident,
            name=r.text("name"),
            capacity=capacidad if capacidad is not None and capacidad >= 0 else None,
            alternative_room=alternativa if alternativa != ident else None,
            room_weight=min(max(r.num("room_weight") or 0, 0), 4),
            department=r.opt("department"),
            text=r.text("special_text"),
        )

    return _unique(una(r) for r in rows if r.text("id"))


def _color_cell(color: str) -> Cell:
    """Color de materia tal cual: número sin comillas si es el entero decimal de
    Untis (`16744448`); cualquier otra forma (`#FF8040`, del XmlInterface) va
    como texto para no perderla."""
    return int(color) if color.isdigit() and str(int(color)) == color else color


def _subject_rows(subjects: Iterable[Subject]) -> Iterator[list[Cell]]:
    for s in subjects:
        marcas = (SUBJECT_FLAG_MAIN if s.main_subject else "") + (
            SUBJECT_FLAG_DOUBLE if s.double_period_required else ""
        )
        yield (
            _RowBuilder(GPU006_COLUMNS)
            .set("id", s.id)
            .set("name", s.name)
            .set("required_room", s.required_room)
            .set("flags", marcas)
            .set("subject_group", s.subject_group)
            .set("fg_color", _color_cell(s.fore_color))
            .set("bg_color", _color_cell(s.back_color))
            .cells
        )


def _read_subjects(rows: Iterable[GpuRow]) -> tuple[Subject, ...]:
    def una(r: GpuRow) -> Subject:
        marcas = r.text("flags")
        return Subject(
            id=r.text("id"),
            name=r.text("name"),
            main_subject=SUBJECT_FLAG_MAIN in marcas,
            double_period_required=SUBJECT_FLAG_DOUBLE in marcas,
            required_room=r.opt("required_room"),
            subject_group=r.opt("subject_group"),
            fore_color=r.text("fg_color"),
            back_color=r.text("bg_color"),
        )

    return _unique(una(r) for r in rows if r.text("id"))


# --------------------------------------------------------------------------- #
# Lecciones: GPU002
# --------------------------------------------------------------------------- #


def _lesson_rows(lessons: Iterable[Lesson]) -> Iterator[list[Cell]]:
    """Una fila por (línea, clase); una línea sin clases ocupa una sola fila.

    `Wochenstd. Kla.` solo lleva los períodos en la primera fila de cada clase
    y `Wochenstd. Le.` en la primera fila de cada línea: así lo hace Untis y es
    la marca que usa la lectura para separar líneas del acople.
    """
    for le in lessons:
        ppw = le.periods_per_week
        marcas = (LESSON_FLAG_FIXED if le.fixed else "") + (LESSON_FLAG_IGNORE if le.ignore else "")
        bloques = (*le.block[:3], None, None, None)
        clases_vistas: set[str] = set()
        for linea in le.lines:
            for k, clase in enumerate(linea.classes or ("",)):
                primera_de_linea = k == 0
                primera_de_clase = bool(clase) and clase not in clases_vistas
                clases_vistas.add(clase)
                yield (
                    _RowBuilder(GPU002_COLUMNS)
                    .set("lesson_number", le.number)
                    .set("periods_per_week", ppw)
                    .set("class_periods", ppw if primera_de_clase else 0)
                    .set("teacher_periods", ppw if primera_de_linea else 0)
                    .set("class", clase)
                    .set("teacher", linea.teacher)
                    .set("subject", linea.subject)
                    .set("room", linea.room)
                    .set(
                        "weekly_value",
                        _decimal(linea.weekly_value) if primera_de_linea else None,
                    )
                    .set("flags", marcas)
                    .set("double_min", le.double_periods.min)
                    .set("double_max", le.double_periods.max)
                    .set("block_size", bloques[0])
                    .set("block_2", bloques[1])
                    .set("block_3", bloques[2])
                    .set("student_group", linea.student_group)
                    .set("line_lesson_group", le.lesson_group)
                    .set("date_from", le.effective_begin)
                    .set("date_to", le.effective_end)
                    .cells
                )


@dataclass(slots=True)
class _LineAcc:
    """Línea en construcción mientras se agrupan las filas de una lección."""

    key: tuple[str | None, str, str | None, str | None]
    classes: list[str]
    weekly_value: float

    def to_line(self) -> LessonLine:
        teacher, subject, room, group = self.key
        return LessonLine(
            subject=subject,
            teacher=teacher,
            classes=tuple(self.classes),
            student_group=group,
            room=room,
            weekly_value=self.weekly_value,
        )


def _split_list(texto: str) -> list[str]:
    return [p.strip() for p in texto.split(LIST_SEPARATOR) if p.strip()]


def _group_lines(rows: Sequence[GpuRow]) -> list[LessonLine]:
    """Reagrupa las filas de una lección en líneas del acople.

    Empieza una línea nueva si: es la primera fila, `Wochenstd. Le.` no es 0,
    cambia (profesor, materia, aula, grupo), la fila no tiene clase o la línea
    en curso tampoco la tenía, o la clase ya estaba en la línea en curso.
    """
    lineas: list[_LineAcc] = []
    for r in rows:
        materia = r.text("subject")
        if not materia:
            continue
        aulas = _split_list(r.text("room"))
        clave = (r.opt("teacher"), materia, aulas[0] if aulas else None, r.opt("student_group"))
        clase = r.text("class")
        clases = [clase] if clase else []
        actual = lineas[-1] if lineas else None
        nueva = (
            actual is None
            or (r.num("teacher_periods") or 0) != 0
            or actual.key != clave
            or not clases
            or not actual.classes
            or any(c in actual.classes for c in clases)
        )
        if nueva or actual is None:
            lineas.append(_LineAcc(clave, clases, r.real("weekly_value") or 0.0))
        else:
            actual.classes.extend(clases)
    return [acc.to_line() for acc in lineas[:LINES_PER_LESSON]]


def _read_lessons(rows: Iterable[GpuRow]) -> tuple[Lesson, ...]:
    por_numero: dict[int, list[GpuRow]] = {}
    for r in rows:
        numero = r.num("lesson_number")
        if numero is not None and numero >= 0:
            por_numero.setdefault(numero, []).append(r)
    lecciones: list[Lesson] = []
    for numero, filas in por_numero.items():
        lineas = _group_lines(filas)
        if not lineas:
            continue
        primera = next(f for f in filas if f.text("subject"))
        marcas = primera.text("flags")
        bloques = tuple(
            b
            for b in (primera.num(c) for c in ("block_size", "block_2", "block_3"))
            if b is not None and b >= 1
        )
        lecciones.append(
            Lesson(
                number=numero,
                lines=tuple(lineas),
                periods_per_week=max(primera.num("periods_per_week") or 0, 0),
                double_periods=_minmax(primera.num("double_min"), primera.num("double_max")),
                block=bloques,
                fixed=LESSON_FLAG_FIXED in marcas,
                ignore=LESSON_FLAG_IGNORE in marcas,
                lesson_group=primera.opt("line_lesson_group"),
                effective_begin=primera.text("date_from"),
                effective_end=primera.text("date_to"),
            )
        )
    return tuple(lecciones)


# --------------------------------------------------------------------------- #
# Horario: GPU001
# --------------------------------------------------------------------------- #


def select_timetable(project: UntisProject, timetable_id: str | None = None) -> Timetable | None:
    """Horario a exportar: el pedido por id o, si no se indica, el último."""
    if timetable_id is not None:
        return project.timetable_by_id(timetable_id)
    return project.timetables[-1] if project.timetables else None


def gpu001_rows(project: UntisProject, timetable: Timetable) -> list[list[Cell]]:
    """Filas de `GPU001.TXT` para un horario.

    Una fila por (asignación, clase de su línea), en el orden de las
    asignaciones; una línea sin clases da una fila con la clase vacía. El aula
    es la colocada (`Assignment.room`), no la pedida por la lección. Las
    asignaciones de lecciones o líneas que el proyecto no define se omiten.
    """
    lecciones = project.lesson_by_number
    # El modelo numera los períodos desde 1; GPU001 usa el rótulo de Untis.
    desplazamiento = project.school.first_period - 1
    filas: list[list[Cell]] = []
    for a in timetable.assignments:
        leccion = lecciones.get(a.lesson_number)
        if leccion is None or a.line >= len(leccion.lines):
            continue
        linea = leccion.lines[a.line]
        for clase in linea.classes or ("",):
            filas.append(
                _RowBuilder(GPU001_COLUMNS)
                .set("lesson_number", a.lesson_number)
                .set("class", clase)
                .set("teacher", linea.teacher)
                .set("subject", linea.subject)
                .set("room", a.room)
                .set("day", a.day)
                .set("period", a.period + desplazamiento)
                .cells
            )
    return filas


def write_gpu001(
    project: UntisProject,
    path: str | Path,
    *,
    timetable_id: str | None = None,
    encoding: str = DEFAULT_ENCODING,
) -> Path:
    """Escribe `GPU001.TXT` (el archivo que consume MiUntisWeb)."""
    horario = select_timetable(project, timetable_id)
    if horario is None:
        raise ValueError(f"El proyecto no tiene el horario {timetable_id or '(ninguno)'}")
    return write_gpu_file(path, gpu001_rows(project, horario), encoding=encoding)


class _LineResolver:
    """Deduce la línea de una fila de GPU001 a partir de las lecciones conocidas."""

    def __init__(self, lessons: Iterable[Lesson]) -> None:
        self._lessons = {le.number: le for le in lessons}
        self._learned: dict[int, list[tuple[str | None, str]]] = {}

    def line_of(self, number: int, cls: str, teacher: str | None, subject: str) -> int | None:
        leccion = self._lessons.get(number)
        if leccion is None:
            # Lección sin GPU002: se numeran las líneas por orden de aparición.
            vistas = self._learned.setdefault(number, [])
            clave = (teacher, subject)
            if clave not in vistas:
                if len(vistas) >= LINES_PER_LESSON:
                    return None
                vistas.append(clave)
            return vistas.index(clave)
        candidatas = [
            i
            for i, ln in enumerate(leccion.lines)
            if ln.subject == subject and ln.teacher == teacher
        ]
        for i in candidatas:
            clases = leccion.lines[i].classes
            if (cls in clases) or (not cls and not clases):
                return i
        return candidatas[0] if candidatas else None


def detect_first_period(rows: Iterable[GpuRow]) -> int:
    """0 si algún período de GPU001 es 0 (colegio con "hora cero"); si no, 1."""
    return 0 if any(r.num("period") == 0 for r in rows) else 1


def _read_timetable(
    rows: Iterable[GpuRow], lessons: Iterable[Lesson], first_period: int = 1
) -> Timetable:
    resolver = _LineResolver(lessons)
    colocadas: dict[tuple[int, int, int, int], Assignment] = {}
    for r in rows:
        numero, dia, rotulo = r.num("lesson_number"), r.num("day"), r.num("period")
        materia = r.text("subject")
        if numero is None or dia is None or rotulo is None or dia < 1:
            continue
        periodo = rotulo - first_period + 1
        if periodo < 1:
            continue
        if not materia:
            continue
        linea = resolver.line_of(numero, r.text("class"), r.opt("teacher"), materia)
        if linea is None:
            continue
        clave = (numero, linea, dia, periodo)
        previa = colocadas.get(clave)
        if previa is None or (previa.room is None and r.opt("room")):
            colocadas[clave] = Assignment(numero, linea, dia, periodo, room=r.opt("room"))
    return Timetable(id=GPU_TIMETABLE_ID, assignments=tuple(colocadas.values()))


def read_gpu001(
    path: str | Path, lessons: Iterable[Lesson] = (), first_period: int | None = None
) -> Timetable:
    """Lee `GPU001.TXT`; con las lecciones de GPU002 resuelve la línea exacta.

    `first_period` es el rótulo del primer período en Untis; `None` lo deduce.
    """
    filas = read_gpu_file(path, GPU001_COLUMNS)
    primero = detect_first_period(filas) if first_period is None else first_period
    return _read_timetable(filas, lessons, primero)


def read_gpu002(path: str | Path) -> tuple[Lesson, ...]:
    """Lee `GPU002.TXT` y reagrupa los acoples en lecciones con N líneas."""
    return _read_lessons(read_gpu_file(path, GPU002_COLUMNS))


def write_gpu002(
    lessons: Iterable[Lesson], path: str | Path, *, encoding: str = DEFAULT_ENCODING
) -> Path:
    """Escribe `GPU002.TXT`."""
    return write_gpu_file(path, _lesson_rows(lessons), encoding=encoding)


# --------------------------------------------------------------------------- #
# Deseos de tiempo: GPU016
# --------------------------------------------------------------------------- #


def _request_rows(requests: Iterable[TimeRequest]) -> Iterator[list[Cell]]:
    """Una fila por deseo; `day`/`period` en `None` se escriben como 0.

    Los deseos de grupos de alumnos no tienen letra en GPU016 y se omiten.
    """
    for rq in requests:
        codigo = REQUEST_KIND_CODES.get(rq.entity_kind)
        if codigo is None:
            continue
        yield (
            _RowBuilder(GPU016_COLUMNS)
            .set("kind", codigo)
            .set("entity_id", rq.entity_id)
            .set("day", rq.day if rq.day is not None else 0)
            .set("period", rq.period if rq.period is not None else 0)
            .set("value", rq.value)
            .cells
        )


def _read_requests(rows: Iterable[GpuRow]) -> tuple[TimeRequest, ...]:
    """Deseos de GPU016. Se omiten los 0 (borrado) y `día=0, período=0`."""
    deseos: list[TimeRequest] = []
    for r in rows:
        tipo = _REQUEST_KIND_BY_CODE.get(r.text("kind").upper())
        ident = r.text("entity_id")
        dia, periodo, valor = r.num("day"), r.num("period"), r.num("value")
        if tipo is None or not ident or dia is None or periodo is None or valor is None:
            continue
        if valor == 0 or not REQUEST_MIN <= valor <= REQUEST_MAX or dia < 0 or periodo < 0:
            continue
        if dia == 0 and periodo == 0:
            continue
        deseos.append(TimeRequest(tipo, ident, valor, day=dia or None, period=periodo or None))
    return tuple(deseos)


def read_gpu016(path: str | Path) -> tuple[TimeRequest, ...]:
    """Lee `GPU016.TXT` (deseos de tiempo -3..+3 por celda)."""
    return _read_requests(read_gpu_file(path, GPU016_COLUMNS))


def write_gpu016(
    requests: Iterable[TimeRequest], path: str | Path, *, encoding: str = DEFAULT_ENCODING
) -> Path:
    """Escribe `GPU016.TXT`."""
    return write_gpu_file(path, _request_rows(requests), encoding=encoding)


# --------------------------------------------------------------------------- #
# Proyecto completo
# --------------------------------------------------------------------------- #


def _find(directory: Path, filename: str) -> Path | None:
    """Busca `filename` en `directory` sin distinguir mayúsculas."""
    exacto = directory / filename
    if exacto.is_file():
        return exacto
    objetivo = filename.upper()
    for candidato in directory.iterdir():
        if candidato.is_file() and candidato.name.upper() == objetivo:
            return candidato
    return None


def read_gpu(directory: str | Path) -> UntisProject:
    """Lee los archivos GPU presentes en `directory` y arma un `UntisProject`.

    Los archivos ausentes dejan su colección vacía. GPU no transporta rejillas,
    grupos de alumnos, períodos lectivos, ponderación ni datos del colegio.
    """
    carpeta = Path(directory)
    if not carpeta.is_dir():
        raise NotADirectoryError(f"No es una carpeta: {carpeta}")

    def filas(layout: GpuLayout) -> list[GpuRow]:
        ruta = _find(carpeta, layout.filename)
        return read_gpu_file(ruta, layout) if ruta is not None else []

    lecciones = _read_lessons(filas(GPU002_COLUMNS))
    filas_horario = filas(GPU001_COLUMNS)
    primero = detect_first_period(filas_horario)
    horarios = (_read_timetable(filas_horario, lecciones, primero),) if filas_horario else ()
    return UntisProject(
        school=SchoolInfo(first_period=primero),
        departments=_read_departments(filas(GPU007_COLUMNS)),
        classes=_read_classes(filas(GPU003_COLUMNS)),
        teachers=_read_teachers(filas(GPU004_COLUMNS)),
        rooms=_read_rooms(filas(GPU005_COLUMNS)),
        subjects=_read_subjects(filas(GPU006_COLUMNS)),
        lessons=lecciones,
        time_requests=_read_requests(filas(GPU016_COLUMNS)),
        timetables=horarios,
    )


def write_gpu(
    project: UntisProject,
    directory: str | Path,
    *,
    encoding: str = DEFAULT_ENCODING,
    timetable_id: str | None = None,
) -> list[Path]:
    """Escribe los archivos GPU del proyecto en `directory` y devuelve sus rutas.

    Siempre escribe GPU002-GPU007 y GPU016 (vacíos si no hay datos); GPU001
    solo si hay horario (`timetable_id` o, por defecto, el último del proyecto).
    Un carácter que no exista en `encoding` no hace fallar: ver `UNTIS_ERRORS`.
    """
    carpeta = Path(directory)
    carpeta.mkdir(parents=True, exist_ok=True)
    tablas: list[tuple[GpuLayout, Iterable[Sequence[Cell]]]] = [
        (GPU002_COLUMNS, _lesson_rows(project.lessons)),
        (GPU003_COLUMNS, _class_rows(project.classes)),
        (GPU004_COLUMNS, _teacher_rows(project.teachers)),
        (GPU005_COLUMNS, _room_rows(project.rooms)),
        (GPU006_COLUMNS, _subject_rows(project.subjects)),
        (GPU007_COLUMNS, _department_rows(project.departments)),
        (GPU016_COLUMNS, _request_rows(project.time_requests)),
    ]
    horario = select_timetable(project, timetable_id)
    if horario is not None:
        tablas.insert(0, (GPU001_COLUMNS, gpu001_rows(project, horario)))
    elif timetable_id is not None:
        raise ValueError(f"El proyecto no tiene el horario {timetable_id!r}")
    return [
        write_gpu_file(carpeta / layout.filename, rows, encoding=encoding)
        for layout, rows in tablas
    ]
