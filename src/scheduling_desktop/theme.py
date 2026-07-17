"""Tema visual de la app (Fase 6): estilo tipo Untis, claro y compacto.

Centraliza la hoja de estilos global (QSS), la paleta de colores por materia
(cada materia con un color estable, como Untis) y los nombres de los días. Es
puramente presentación; ningún dato ni regla vive aquí.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

# --- paleta base ----------------------------------------------------------- #
PRIMARY = "#2563eb"
PRIMARY_DARK = "#1d4ed8"
BG = "#eef2f7"
PANEL = "#ffffff"
BORDER = "#c7d2e0"
HEADER_BG = "#dbe4f0"
INK = "#0f172a"
MUTED = "#64748b"
SELECTION = "#dbeafe"
SELECTION_INK = "#1e3a8a"
CHROME = "#1e293b"

APP_QSS = f"""
* {{ font-size: 13px; }}
QMainWindow, QWidget {{ background: {BG}; color: {INK}; }}

QMenuBar {{ background: {CHROME}; color: #e2e8f0; padding: 2px; }}
QMenuBar::item {{ background: transparent; padding: 6px 12px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: #334155; }}
QMenu {{ background: {PANEL}; color: {INK}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {SELECTION}; color: {SELECTION_INK}; }}

QToolBar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f8fafc, stop:1 #e2e8f0);
            border-bottom: 1px solid {BORDER}; spacing: 4px; padding: 5px; }}
QToolBar QToolButton {{ padding: 7px 12px; border-radius: 6px; font-weight: 600; color: {INK}; }}
QToolBar QToolButton:hover {{ background: #cdd9ea; }}
QToolBar QToolButton:pressed {{ background: #b8c8de; }}

QStatusBar {{ background: {CHROME}; color: #cbd5e1; }}
QStatusBar QLabel {{ color: #cbd5e1; }}

QPushButton {{ background: {PRIMARY}; color: white; border: none; padding: 7px 14px;
               border-radius: 6px; font-weight: 600; }}
QPushButton:hover {{ background: {PRIMARY_DARK}; }}
QPushButton:disabled {{ background: #9aa8bd; color: #eef2f7; }}

QTableView, QTreeWidget, QTreeView, QListWidget {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: #e6ebf2; selection-background-color: {SELECTION};
    selection-color: {SELECTION_INK}; outline: 0; }}
QTableView {{ alternate-background-color: #f6f8fc; }}
QListWidget::item {{ padding: 6px 8px; border-bottom: 1px solid #eef2f7; }}
QListWidget::item:selected {{ background: {SELECTION}; color: {SELECTION_INK}; }}

QHeaderView::section {{ background: {HEADER_BG}; color: {CHROME}; padding: 7px 8px;
    border: none; border-right: 1px solid {BORDER}; border-bottom: 1px solid {BORDER};
    font-weight: 700; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px;
    background: {PANEL}; top: -1px; }}
QTabBar::tab {{ background: #e2e8f0; color: {MUTED}; padding: 7px 16px; margin-right: 2px;
    border-top-left-radius: 7px; border-top-right-radius: 7px; font-weight: 600; }}
QTabBar::tab:selected {{ background: {PANEL}; color: {PRIMARY_DARK}; }}
QTabBar::tab:hover {{ color: {INK}; }}

QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {HEADER_BG}; padding: 7px; font-weight: 700; color: {CHROME}; }}

QComboBox, QSpinBox, QDoubleSpinBox {{ background: {PANEL}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 4px 8px; }}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {PRIMARY}; }}

QProgressBar {{ border: 1px solid {BORDER}; border-radius: 7px; background: {PANEL};
    text-align: center; height: 18px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
    stop:0 {PRIMARY}, stop:1 #38bdf8); border-radius: 6px; }}

QSlider::groove:horizontal {{ height: 6px; background: #cbd5e1; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {PRIMARY}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {PANEL}; border: 2px solid {PRIMARY};
    width: 16px; margin: -7px 0; border-radius: 9px; }}

QPlainTextEdit {{ background: #0f172a; color: #d1fae5; border: 1px solid {BORDER};
    border-radius: 8px; font-family: Consolas, monospace; }}
QCheckBox {{ spacing: 8px; }}
"""

# --- colores de materia (estables por nombre, como Untis) ------------------ #
_SUBJECT_PALETTE = (
    "#fde68a",
    "#bfdbfe",
    "#bbf7d0",
    "#fbcfe8",
    "#c7d2fe",
    "#fed7aa",
    "#a7f3d0",
    "#ddd6fe",
    "#fecaca",
    "#99f6e4",
    "#f5d0fe",
    "#d9f99d",
)


def subject_color(name: str) -> QColor:
    """Color estable para una materia (mismo nombre -> mismo color)."""
    index = sum(ord(c) for c in name) % len(_SUBJECT_PALETTE)
    return QColor(_SUBJECT_PALETTE[index])


_DAYS_ES = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def day_name(index: int, total: int) -> str:
    """Nombre del día: usa la semana si son <= 7 días; si no, 'Día N'."""
    if total <= len(_DAYS_ES):
        return _DAYS_ES[index]
    return f"Día {index + 1}"
