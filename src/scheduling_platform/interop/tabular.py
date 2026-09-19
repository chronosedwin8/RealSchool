"""Tablas de texto (CSV/TSV): de un archivo o de un texto a filas de diccionarios.

Es la puerta para que un colegio meta sus datos de golpe: exporta la cuadrícula,
la edita en Excel o en LibreOffice y la vuelve a importar. Este módulo es
genérico a propósito -no sabe nada de clases ni de profesores-: solo convierte
texto tabulado en filas `encabezado -> valor`. Quién es cada columna lo decide la
capa de aplicación (`application.untis.bulk`), que es la que conoce las
etiquetas; así `interop` sigue sin depender de nadie más que del modelo.

Reglas del formato:

- **Encabezado obligatorio**: la primera línea con algo escrito da los nombres de
  las columnas. Sin encabezado no hay filas.
- **Delimitador deducido del encabezado**: `;`, `,` o tabulador, el que más
  aparezca (al empatar gana el de la lista, en ese orden). Se puede imponer uno.
- **Codificación deducida**: `utf-8` con o sin BOM (lo que escribe Excel) y
  `cp1252` (Windows occidental) como último recurso.
- Comillas al estilo CSV: un valor entre comillas puede llevar el delimitador,
  comillas dobladas y saltos de línea.
- **Nunca lanza por un dato malo**: lo que no se pueda leer sale en `errors`,
  con el número de fila y el nombre de la columna.

Los números de fila son los que ve el usuario en su hoja de cálculo: `1` es la
primera fila de datos (la de debajo del encabezado) y `0` es el encabezado.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

#: Delimitadores reconocidos, por orden de preferencia cuando hay empate.
DELIMITERS: Final[tuple[str, ...]] = (";", ",", "\t")

#: Codificaciones que se prueban, en este orden.
ENCODINGS: Final[tuple[str, ...]] = ("utf-8-sig", "utf-8", "cp1252")

#: Marca de orden de bytes que Excel pone al principio de sus CSV en UTF-8.
BOM: Final[bytes] = b"\xef\xbb\xbf"

#: Delimitador que se usa cuando el encabezado no trae ninguno (una columna).
DEFAULT_DELIMITER: Final[str] = ";"

#: Final de línea al escribir (RFC 4180; Excel y LibreOffice lo esperan así).
LINE_END: Final[str] = "\r\n"


@dataclass(frozen=True, slots=True)
class TableError:
    """Algo que no se pudo leer: `row` 0 es el encabezado; `column` puede ir vacío."""

    row: int
    column: str
    message: str

    def render(self) -> str:
        sitio = f"fila {self.row}" if self.row else "encabezado"
        if self.column:
            sitio = f"{sitio}, columna «{self.column}»"
        return f"{sitio}: {self.message}"


@dataclass(frozen=True, slots=True)
class TableRow:
    """Una fila de datos: `número de fila` y `encabezado -> texto` (ya recortado)."""

    number: int
    cells: dict[str, str] = field(default_factory=dict)

    def get(self, column: str) -> str:
        return self.cells.get(column, "")


@dataclass(frozen=True, slots=True)
class Table:
    """Resultado de leer una tabla: encabezados, filas y lo que no se pudo leer."""

    headers: tuple[str, ...] = ()
    rows: tuple[TableRow, ...] = ()
    errors: tuple[TableError, ...] = ()
    delimiter: str = DEFAULT_DELIMITER
    encoding: str = ""
    """Codificación con la que se leyó el archivo ("" si la fuente ya era texto)."""

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------- #
# Codificación y delimitador
# --------------------------------------------------------------------------- #


def decode(data: bytes) -> tuple[str, str]:
    """Texto y nombre de la codificación con la que se pudo leer `data`."""
    if data.startswith(BOM):
        return data.decode("utf-8-sig"), "utf-8-sig"
    for nombre in ENCODINGS:
        if nombre == "utf-8-sig":
            continue  # sin BOM no aporta nada: "utf-8" dice mejor lo que se leyó
        try:
            return data.decode(nombre), nombre
        except UnicodeDecodeError:
            continue
    # cp1252 tiene unos pocos bytes sin asignar: antes de rendirse, se sustituyen.
    return data.decode("cp1252", errors="replace"), "cp1252"


def detect_delimiter(header: str) -> str:
    """Delimitador del encabezado: el que más veces aparece fuera de comillas."""
    fuera: list[str] = []
    entre_comillas = False
    for caracter in header:
        if caracter == '"':
            entre_comillas = not entre_comillas
        elif not entre_comillas:
            fuera.append(caracter)
    cuentas = {d: fuera.count(d) for d in DELIMITERS}
    mejor = max(DELIMITERS, key=lambda d: cuentas[d])
    return mejor if cuentas[mejor] else DEFAULT_DELIMITER


def load_text(source: str | Path) -> tuple[str, str]:
    """Texto y codificación de la fuente: una ruta se lee, un texto se usa tal cual.

    Una cadena con saltos de línea es siempre texto; una sin ellos se prueba
    como ruta de archivo y, si no existe, también se toma como texto.
    """
    if isinstance(source, Path):
        return decode(source.read_bytes())
    if "\n" in source or "\r" in source:
        return source, ""
    try:
        ruta = Path(source)
        es_archivo = ruta.is_file()
    except OSError, ValueError:
        return source, ""
    return decode(ruta.read_bytes()) if es_archivo else (source, "")


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #


def _first_line(text: str) -> str:
    """Primera línea con algo escrito (la del encabezado)."""
    for linea in text.splitlines():
        if linea.strip():
            return linea
    return ""


def _clean_headers(crudos: list[str], errores: list[TableError]) -> tuple[str, ...]:
    """Encabezados recortados, sin los vacíos y sin repetidos (gana el primero)."""
    limpios: list[str] = []
    vistos: set[str] = set()
    for nombre in crudos:
        texto = nombre.strip()
        if not texto:
            continue  # columna sin nombre (coma de más de Excel): se ignora.
        if texto in vistos:
            errores.append(TableError(0, texto, f"Columna repetida: {texto!r}"))
            continue
        vistos.add(texto)
        limpios.append(texto)
    return tuple(limpios)


def _row(numero: int, headers: tuple[str, ...], celdas: list[str]) -> tuple[TableRow, str]:
    """Fila con `encabezado -> texto`; el segundo valor es el motivo si sobran datos."""
    aviso = ""
    if len(celdas) > len(headers) and any(c.strip() for c in celdas[len(headers) :]):
        aviso = f"La fila trae {len(celdas)} valores y el encabezado {len(headers)} columnas"
    valores = {h: (celdas[i].strip() if i < len(celdas) else "") for i, h in enumerate(headers)}
    return TableRow(numero, valores), aviso


def read_table(source: str | Path, *, delimiter: str | None = None) -> Table:
    """Lee una tabla de un archivo o de un texto. Nunca lanza por un dato malo."""
    errores: list[TableError] = []
    try:
        texto, codificacion = load_text(source)
    except OSError as exc:
        return Table(errors=(TableError(0, "", f"No se pudo leer el archivo: {exc}"),))
    if not texto.strip():
        return Table(
            errors=(TableError(0, "", "La tabla está vacía: hace falta una fila de encabezado"),),
            encoding=codificacion,
        )
    separador = delimiter or detect_delimiter(_first_line(texto))
    lector = csv.reader(io.StringIO(texto, newline=""), delimiter=separador, skipinitialspace=True)
    try:
        crudas = [linea for linea in lector if any(c.strip() for c in linea)]
    except csv.Error as exc:
        return Table(
            errors=(TableError(0, "", f"Texto mal formado: {exc}"),),
            delimiter=separador,
            encoding=codificacion,
        )
    if not crudas:
        return Table(
            errors=(TableError(0, "", "La tabla está vacía: hace falta una fila de encabezado"),),
            delimiter=separador,
            encoding=codificacion,
        )
    headers = _clean_headers(crudas[0], errores)
    if not headers:
        errores.append(TableError(0, "", "El encabezado no tiene ninguna columna con nombre"))
        return Table(errors=tuple(errores), delimiter=separador, encoding=codificacion)
    filas: list[TableRow] = []
    for numero, celdas in enumerate(crudas[1:], start=1):
        fila, aviso = _row(numero, headers, celdas)
        if aviso:
            errores.append(TableError(numero, "", aviso))
            continue
        filas.append(fila)
    return Table(headers, tuple(filas), tuple(errores), separador, codificacion)


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #


def write_table(
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    *,
    delimiter: str = DEFAULT_DELIMITER,
) -> str:
    """Texto CSV con el encabezado y las filas (entrecomilla lo que haga falta)."""
    salida = io.StringIO(newline="")
    escritor = csv.writer(salida, delimiter=delimiter, lineterminator=LINE_END)
    escritor.writerow(headers)
    escritor.writerows(rows)
    return salida.getvalue()


def write_file(
    path: str | Path,
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    *,
    delimiter: str = DEFAULT_DELIMITER,
    encoding: str = "utf-8-sig",
) -> Path:
    """Escribe la tabla en un archivo (por defecto en UTF-8 con BOM, como Excel)."""
    destino = Path(path)
    destino.write_text(
        write_table(headers, rows, delimiter=delimiter), encoding=encoding, newline=""
    )
    return destino
