"""Horarios en HTML: una tabla por entidad, días en columnas y períodos en filas.

Es la exportación que se publica en la web del colegio y la base del PDF. El
formato de celda (`TimetableFormat`) decide qué campos se ven (materia,
profesor, aula, clase), el tamaño de letra y si se pinta el color de la
materia; es el mismo que usa la ventana Horarios en pantalla.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass

from scheduling_platform.application import PeriodRow, TimetableGrid, UntisTimetableCell

from ..i18n import tr
from ..theme import BREAK_COLOR, CONFLICT_COLOR, day_name, subject_color

_CONTEXT = "TimetableExport"


@dataclass(frozen=True, slots=True)
class TimetableFormat:
    """Qué muestra cada celda de un horario."""

    subject: bool = True
    teacher: bool = True
    room: bool = True
    school_class: bool = False
    font_size: int = 9
    colors: bool = True


#: Formatos predefinidos (clave estable -> formato). Las etiquetas las pone la UI.
FORMATS: dict[str, TimetableFormat] = {
    "class": TimetableFormat(subject=True, teacher=True, room=True, school_class=False),
    "teacher": TimetableFormat(subject=True, teacher=False, room=True, school_class=True),
    "room": TimetableFormat(subject=True, teacher=True, room=False, school_class=True),
    "full": TimetableFormat(subject=True, teacher=True, room=True, school_class=True),
    "compact": TimetableFormat(
        subject=True, teacher=False, room=False, school_class=False, font_size=8
    ),
    "print": TimetableFormat(subject=True, teacher=True, room=True, colors=False, font_size=10),
}


def period_minutes(period: PeriodRow) -> int:
    """Duración de un período en minutos (`HH:MM` - `HH:MM`)."""

    def minutos(texto: str) -> int:
        horas, _, mins = texto.partition(":")
        try:
            return int(horas) * 60 + int(mins or 0)
        except ValueError:
            return 0

    return max(0, minutos(period.end) - minutos(period.start))


def cell_lines(cells: Sequence[UntisTimetableCell], fmt: TimetableFormat) -> list[str]:
    """Líneas de texto de una celda; varias lecciones a la vez se separan con `/`."""
    lineas: list[str] = []
    for campo, activo in (
        ("subject", fmt.subject),
        ("teacher", fmt.teacher),
        ("room", fmt.room),
        ("class", fmt.school_class),
    ):
        if not activo:
            continue
        valores: list[str] = []
        for c in cells:
            if campo == "subject":
                texto = c.subject
            elif campo == "teacher":
                texto = ", ".join(c.teachers)
            elif campo == "room":
                texto = ", ".join(c.rooms)
            else:
                texto = ", ".join(c.classes)
            if texto:
                valores.append(texto)
        if valores:
            lineas.append(" / ".join(dict.fromkeys(valores)))
    return lineas


_CSS = """
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: {size}pt; color: #111827; }}
h1 {{ font-size: {title}pt; margin: 12px 0 4px 0; }}
table.tt {{ border-collapse: collapse; width: 100%; margin-bottom: 18px; }}
table.tt th, table.tt td {{ border: 1px solid #9ca3af; padding: 3px; text-align: center;
  vertical-align: middle; }}
table.tt th {{ background: #e5e7eb; }}
td.period {{ background: #f3f4f6; white-space: nowrap; }}
td.break {{ background: {pause}; }}
td.conflict {{ border: 2px solid {conflict}; }}
td.fixed {{ font-weight: bold; }}
.page {{ page-break-before: always; }}
"""


def _cell_html(cells: Sequence[UntisTimetableCell], fmt: TimetableFormat, is_break: bool) -> str:
    if is_break:
        return f'<td class="break" bgcolor="{BREAK_COLOR}"></td>'
    if not cells:
        return "<td></td>"
    clases = []
    if any(c.conflict for c in cells):
        clases.append("conflict")
    if any(c.fixed for c in cells):
        clases.append("fixed")
    atributos = f' class="{" ".join(clases)}"' if clases else ""
    if fmt.colors:
        color = subject_color(cells[0].subject, cells[0].color).name()
        atributos += f' bgcolor="{color}" style="background-color: {color};"'
    texto = "<br/>".join(html.escape(linea) for linea in cell_lines(cells, fmt))
    return f"<td{atributos}>{texto}</td>"


def _table_html(grid: TimetableGrid, fmt: TimetableFormat, language: str) -> str:
    cabecera = "".join(f"<th>{html.escape(day_name(d, language))}</th>" for d in grid.days)
    filas = [f"<tr><th>{html.escape(tr(_CONTEXT, 'Período'))}</th>{cabecera}</tr>"]
    for periodo in grid.periods:
        etiqueta = f"{periodo.number}<br/>{periodo.start}-{periodo.end}"
        celdas = "".join(
            _cell_html(grid.at(dia, periodo.number), fmt, periodo.is_break) for dia in grid.days
        )
        filas.append(f'<tr><td class="period">{etiqueta}</td>{celdas}</tr>')
    cuerpo = "\n".join(filas)
    return f'<table class="tt" cellspacing="0" cellpadding="3" border="1">\n{cuerpo}\n</table>'


def timetable_html(
    grids: Sequence[TimetableGrid],
    fmt: TimetableFormat | None = None,
    *,
    language: str = "es",
    title: str = "",
) -> str:
    """Documento HTML completo con un horario (tabla) por entidad.

    Cada entidad a partir de la segunda empieza página nueva al imprimir.
    """
    formato = fmt if fmt is not None else FORMATS["class"]
    css = _CSS.format(
        size=formato.font_size,
        title=formato.font_size + 5,
        pause=BREAK_COLOR,
        conflict=CONFLICT_COLOR,
    )
    if title:
        titulo = title
    elif len(grids) == 1:
        titulo = grids[0].title
    else:
        titulo = tr(_CONTEXT, "Horarios")
    partes = [
        "<!DOCTYPE html>",
        f'<html lang="{html.escape(language)}">',
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>{html.escape(titulo)}</title>",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
    ]
    for i, grid in enumerate(grids):
        clase = ' class="page"' if i else ""
        partes.append(f"<div{clase}>")
        partes.append(f"<h1>{html.escape(grid.title)}</h1>")
        partes.append(_table_html(grid, formato, language))
        partes.append("</div>")
    partes += ["</body>", "</html>", ""]
    return "\n".join(partes)
