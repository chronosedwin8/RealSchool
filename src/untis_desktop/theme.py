"""Colores y estilo comunes de la UI (propios, no los de Untis)."""

from __future__ import annotations

import hashlib

from PySide6.QtGui import QColor

APP_QSS = """
QMainWindow { background: #f3f4f6; }
QTabWidget#ribbon QToolBar { spacing: 6px; padding: 2px; }
QTableView { gridline-color: #d1d5db; selection-background-color: #bfdbfe;
             selection-color: #111827; }
QHeaderView::section { background: #e5e7eb; padding: 3px; border: 0;
                       border-right: 1px solid #d1d5db; }
"""

#: Escala de deseos -3 (imposible) .. +3 (muy deseable): rojo -> blanco -> verde.
REQUEST_COLORS: dict[int, str] = {
    -3: "#b91c1c",
    -2: "#ef4444",
    -1: "#fca5a5",
    0: "#ffffff",
    1: "#bbf7d0",
    2: "#4ade80",
    3: "#15803d",
}

#: Celda con error de validación (edición rechazada, carga excedida...).
ERROR_COLOR = "#fecaca"
#: Celda de recreo en rejillas y horarios.
BREAK_COLOR = "#e5e7eb"
#: Horas cerradas con un deseo -3: trama gris sobre la celda.
BLOCKED_COLOR = "#6b7280"
#: Conflicto en el Diálogo de planificación / horarios.
CONFLICT_COLOR = "#f87171"
#: Destino válido al arrastrar en el Diálogo de planificación.
TARGET_OK_COLOR = "#86efac"
#: Destino imposible al arrastrar.
TARGET_NO_COLOR = "#fca5a5"

_PALETTE = (
    "#93c5fd", "#fcd34d", "#a7f3d0", "#f9a8d4", "#c4b5fd", "#fdba74",
    "#99f6e4", "#fde68a", "#bef264", "#f0abfc", "#a5b4fc", "#fda4af",
)  # fmt: skip


def request_color(value: int) -> QColor:
    """Color de un deseo -3..+3."""
    return QColor(REQUEST_COLORS.get(max(-3, min(3, value)), "#ffffff"))


def subject_color(subject: str, stored: str = "") -> QColor:
    """Color de una materia: el guardado en el proyecto o uno estable por nombre."""
    if stored:
        texto = stored.strip()
        if texto.startswith("#") and len(texto) in (4, 7):
            return QColor(texto)
        if texto.isdigit():  # color decimal de Untis (BGR)
            n = int(texto)
            return QColor(n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF)
    indice = int(hashlib.sha1(subject.encode("utf-8")).hexdigest(), 16) % len(_PALETTE)
    return QColor(_PALETTE[indice])


DAY_NAMES_ES = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
DAY_NAMES_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def day_name(day: int, language: str = "es") -> str:
    """Nombre del día Untis (1 = lunes)."""
    nombres = DAY_NAMES_DE if language == "de" else DAY_NAMES_ES
    return nombres[(day - 1) % 7]


def fmt_int(value: int) -> str:
    """Entero con separador de miles legible (`1218418` -> `1.218.418`)."""
    return f"{value:,}".replace(",", ".")


def text_color_for(background: QColor) -> QColor:
    """Negro o blanco, el que mejor se lea sobre `background` (luminancia WCAG)."""

    def canal(c: int) -> float:
        x = c / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    lum = (
        0.2126 * canal(background.red())
        + 0.7152 * canal(background.green())
        + 0.0722 * canal(background.blue())
    )
    return QColor("#111827") if lum > 0.35 else QColor("#ffffff")
