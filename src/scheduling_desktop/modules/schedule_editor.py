"""Módulo 4 · Schedule Editor: la rejilla semanal del horario (solo vista).

Dibuja la rejilla día x período (``QGraphicsView``) del recurso en foco
(docente/grupo/aula); los conflictos se pintan en rojo. v1 es de solo lectura;
el drag&drop con reoptimización llega en un milestone posterior. Toda la
ubicación de clases la calcula el motor (``TimetableView``).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import TimetableCell, TimetableView

from ..engine_bridge import EngineBridge

_CELL_W = 150.0
_CELL_H = 64.0
_HEAD = 34.0
_NORMAL = QColor("#3b82f6")
_CONFLICT = QColor("#ef4444")
_GRID = QColor("#cbd5e1")


class ScheduleEditorModule(QWidget):
    """Vista semanal del horario por docente/grupo/aula."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._focus = QComboBox()
        self._focus.currentIndexChanged.connect(self._redraw)

        top = QHBoxLayout()
        top.addWidget(QLabel("Ver por:"))
        top.addWidget(self._focus, stretch=1)

        self._scene = QGraphicsScene()
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._view, stretch=1)

        bridge.session_changed.connect(self.refresh)

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        previous = self._focus.currentData()
        self._focus.blockSignals(True)
        self._focus.clear()
        for option in self._bridge.focus_options():
            label = {"teacher": "Docente", "group": "Grupo", "room": "Aula"}.get(
                option.kind, option.kind
            )
            self._focus.addItem(f"{label}: {option.name}", option.resource_id)
        index = self._focus.findData(previous)
        self._focus.setCurrentIndex(index if index >= 0 else 0)
        self._focus.blockSignals(False)
        self._redraw()

    def _redraw(self) -> None:
        self._scene.clear()
        if not self._bridge.has_session or self._focus.count() == 0:
            return
        focus_id = self._focus.currentData()
        if not isinstance(focus_id, int):
            return
        view = self._bridge.timetable(focus_id)
        self._draw_grid(view)
        for cell in view.cells:
            self._draw_cell(view, cell)

    def _draw_grid(self, view: TimetableView) -> None:
        pen = QPen(_GRID)
        header = QFont()
        header.setBold(True)
        for day in range(view.days):
            x = _HEAD + day * _CELL_W
            text = self._scene.addText(f"Día {day + 1}", header)
            text.setPos(x + 8, 6)
            for period in range(view.periods_per_day):
                y = _HEAD + period * _CELL_H
                self._scene.addRect(x, y, _CELL_W, _CELL_H, pen)
        for period in range(view.periods_per_day):
            y = _HEAD + period * _CELL_H
            label = self._scene.addText(f"P{period + 1}")
            label.setPos(2, y + _CELL_H / 2 - 10)

    def _draw_cell(self, view: TimetableView, cell: TimetableCell) -> None:
        x = _HEAD + cell.day * _CELL_W
        y = _HEAD + cell.period * _CELL_H
        rect = QRectF(x + 2, y + 2, _CELL_W - 4, cell.duration * _CELL_H - 4)
        color = _CONFLICT if cell.conflict else _NORMAL
        self._scene.addRect(rect, QPen(color.darker()), QBrush(color.lighter(160)))

        detail = cell.group if view.focus_kind != "group" else cell.teacher
        text = self._scene.addText(f"{cell.subject}\n{detail}\n{cell.room}")
        text.setDefaultTextColor(QColor("#0f172a"))
        text.setPos(x + 8, y + 6)
        text.setTextWidth(_CELL_W - 16)
