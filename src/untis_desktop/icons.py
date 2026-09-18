"""Iconos de la interfaz: nombres semánticos -> SVG de Lucide coloreado.

Los SVG vienen de Lucide (licencia ISC, `icons/LICENSE.txt`), un juego genérico
de iconos de trazo: no se usa ningún icono de Untis. Cada acción pide su icono
por **lo que hace** (`icon("optimize")`), no por el archivo, y cada familia de
herramientas tiene su color para reconocerla de un vistazo:

- azul: archivo y datos maestros;
- violeta: lecciones y planificación;
- verde: generar, optimizar, confirmar;
- ámbar: avisos, deseos, fijar;
- rojo: borrar, detener, errores;
- gris: vista, ayuda y utilidades.

Los SVG usan `stroke="currentColor"`; se sustituye por el color de la familia
antes de rasterizar, así un solo archivo sirve para cualquier color.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Final

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICONS_DIR: Final = Path(__file__).parent / "icons"

BLUE: Final = "#2563eb"
VIOLET: Final = "#7c3aed"
GREEN: Final = "#16a34a"
AMBER: Final = "#d97706"
RED: Final = "#dc2626"
GREY: Final = "#475569"
TEAL: Final = "#0d9488"

#: Nombre semántico -> (archivo SVG sin extensión, color).
ICONS: Final[dict[str, tuple[str, str]]] = {
    # --- archivo -----------------------------------------------------------
    "new": ("file-plus", BLUE),
    "open": ("folder-open", BLUE),
    "save": ("save", BLUE),
    "save_as": ("save-all", BLUE),
    "undo": ("undo-2", GREY),
    "redo": ("redo-2", GREY),
    "import": ("download", BLUE),
    "export": ("upload", BLUE),
    "settings": ("settings", GREY),
    "school": ("school", BLUE),
    "wizard": ("sparkles", GREEN),
    # --- datos maestros ------------------------------------------------------
    "classes": ("users", BLUE),
    "teachers": ("graduation-cap", BLUE),
    "rooms": ("door-open", BLUE),
    "subjects": ("book-open", BLUE),
    "departments": ("building-2", BLUE),
    "student_groups": ("users-round", BLUE),
    "time_grids": ("clock", TEAL),
    "grid_add": ("calendar-plus", TEAL),
    "grid_remove": ("calendar-x", RED),
    "period_add": ("rows-3", TEAL),
    "requests": ("hand-heart", AMBER),
    # --- lecciones -----------------------------------------------------------
    "lessons": ("list-checks", VIOLET),
    "couple": ("link", VIOLET),
    "uncouple": ("unlink", VIOLET),
    "lesson_add": ("plus", GREEN),
    # --- módulos -------------------------------------------------------------
    "weighting": ("sliders-horizontal", VIOLET),
    "analysis": ("bar-chart-3", VIOLET),
    # --- horarios -------------------------------------------------------------
    "optimize": ("wand-sparkles", GREEN),
    "start": ("circle-play", GREEN),
    "stop": ("circle-stop", RED),
    "repair": ("wrench", GREEN),
    "evaluation": ("gauge", GREEN),
    "diagnosis": ("stethoscope", AMBER),
    "planning": ("calendar-clock", VIOLET),
    "timetables": ("calendar-range", TEAL),
    "history": ("history", GREY),
    "compare": ("scale", GREY),
    "activate": ("check-circle-2", GREEN),
    # --- edición genérica ------------------------------------------------------
    "add": ("plus", GREEN),
    "remove": ("minus", RED),
    "delete": ("trash-2", RED),
    "copy": ("copy", GREY),
    "rename": ("pencil", GREY),
    "fix": ("pin", AMBER),
    "unfix": ("pin-off", AMBER),
    "unplace": ("x-circle", RED),
    "swap": ("arrow-left-right", VIOLET),
    "shuffle": ("shuffle", VIOLET),
    "search": ("search", GREY),
    "filter": ("filter", GREY),
    "columns": ("columns-3", GREY),
    "order": ("list-ordered", GREY),
    # --- salida ---------------------------------------------------------------
    "print": ("printer", GREY),
    "pdf": ("file-text", RED),
    "html": ("file-code-2", BLUE),
    "gpu": ("file-down", TEAL),
    "table": ("table-2", TEAL),
    # --- vista y ayuda ---------------------------------------------------------
    "tile": ("layout-grid", GREY),
    "cascade": ("layers", GREY),
    "language": ("languages", GREY),
    "help": ("help-circle", GREY),
    "info": ("info", BLUE),
    "tip": ("lightbulb", AMBER),
    "steps": ("route", GREEN),
    "launch": ("rocket", GREEN),
    # --- estados ---------------------------------------------------------------
    "ok": ("check-circle-2", GREEN),
    "error": ("x-circle", RED),
    "warning": ("alert-triangle", AMBER),
    "break": ("coffee", GREY),
    "morning": ("sun", AMBER),
    "afternoon": ("moon", VIOLET),
    "locked": ("lock", GREY),
    "unlocked": ("unlock", GREY),
    "visible": ("eye", GREY),
    "drag": ("grip-vertical", GREY),
}

#: Tamaños a los que se rasteriza cada icono (Qt elige el más cercano).
_SIZES: Final = (16, 20, 24, 32, 48)


@cache
def _svg(file: str) -> str:
    return (ICONS_DIR / f"{file}.svg").read_text(encoding="utf-8")


def _pixmap(svg: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


@cache
def icon(name: str, color: str | None = None) -> QIcon:
    """Icono de la acción `name`. Un nombre desconocido es un error de programación."""
    try:
        archivo, color_familia = ICONS[name]
    except KeyError as exc:
        raise KeyError(f"Icono desconocido: {name!r}") from exc
    svg = _svg(archivo).replace("currentColor", color or color_familia)
    resultado = QIcon()
    for size in _SIZES:
        resultado.addPixmap(_pixmap(svg, size), QIcon.Mode.Normal)
    # Estado desactivado: el mismo trazo en gris claro.
    gris = _svg(archivo).replace("currentColor", "#cbd5e1")
    for size in _SIZES:
        resultado.addPixmap(_pixmap(gris, size), QIcon.Mode.Disabled)
    return resultado


def icon_size(kind: str = "button") -> QSize:
    """Tamaño estándar: `ribbon` (cinta), `button` (botones), `small` (celdas, árboles)."""
    return {"ribbon": QSize(28, 28), "button": QSize(18, 18), "small": QSize(16, 16)}[kind]


def names() -> tuple[str, ...]:
    return tuple(ICONS)
