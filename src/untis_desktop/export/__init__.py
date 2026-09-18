"""Exportación de horarios: HTML (con CSS) y PDF (vía `QPrinter`).

`html` genera el documento a partir de los modelos de vista de la Fachada
(`TimetableGrid`) y de un formato de celda; `pdf` lo imprime a PDF con
`QTextDocument`. Ninguno toca el modelo de dominio.
"""

from .html import FORMATS, TimetableFormat, cell_lines, period_minutes, timetable_html
from .pdf import html_to_pdf, print_html

__all__ = [
    "FORMATS",
    "TimetableFormat",
    "cell_lines",
    "html_to_pdf",
    "period_minutes",
    "print_html",
    "timetable_html",
]
