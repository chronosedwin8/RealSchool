"""Módulo 4 · Schedule Editor: la rejilla semanal del horario (solo vista).

Dibuja la rejilla día x período (``QGraphicsView``) del recurso en foco
(docente/grupo/aula); los conflictos se pintan en rojo. v1 es de solo lectura;
el drag&drop con reoptimización llega en un milestone posterior. Toda la
ubicación de clases la calcula el motor (``TimetableView``).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
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
from ..theme import day_name, subject_color

_CELL_W = 158.0
_CELL_H = 66.0
_HEAD = 40.0
_ROWHEAD = 46.0
_CONFLICT = QColor("#ef4444")
_GRID = QColor("#c7d2e0")
_HEADER_BG = QColor("#dbe4f0")
_INK = QColor("#0f172a")


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
        header.setPointSize(10)
        width = _ROWHEAD + view.days * _CELL_W
        height = _HEAD + view.periods_per_day * _CELL_H
        # Franjas de encabezado (día arriba, período a la izquierda).
        self._scene.addRect(0, 0, width, _HEAD, QPen(Qt.PenStyle.NoPen), QBrush(_HEADER_BG))
        self._scene.addRect(0, 0, _ROWHEAD, height, QPen(Qt.PenStyle.NoPen), QBrush(_HEADER_BG))
        for day in range(view.days):
            x = _ROWHEAD + day * _CELL_W
            text = self._scene.addText(day_name(day, view.days), header)
            text.setDefaultTextColor(_INK)
            text.setPos(x + 10, 10)
            for period in range(view.periods_per_day):
                y = _HEAD + period * _CELL_H
                self._scene.addRect(x, y, _CELL_W, _CELL_H, pen)
        for period in range(view.periods_per_day):
            y = _HEAD + period * _CELL_H
            label = self._scene.addText(f"P{period + 1}", header)
            label.setDefaultTextColor(_INK)
            label.setPos(8, y + _CELL_H / 2 - 12)

    def _draw_cell(self, view: TimetableView, cell: TimetableCell) -> None:
        x = _ROWHEAD + cell.day * _CELL_W
        y = _HEAD + cell.period * _CELL_H
        rect = QRectF(x + 3, y + 3, _CELL_W - 6, cell.duration * _CELL_H - 6)
        fill = subject_color(cell.subject)
        border = QPen(_CONFLICT if cell.conflict else fill.darker(140))
        border.setWidth(3 if cell.conflict else 1)
        item = self._scene.addRect(rect, border, QBrush(fill))
        item.setData(0, cell.task_id)

        detail = cell.group if view.focus_kind == "teacher" else cell.teacher
        subject = self._scene.addText("")
        subject.setHtml(
            f"<b>{cell.subject}</b><br>{detail}<br><span style='color:#475569'>{cell.room}</span>"
        )
        subject.setDefaultTextColor(_INK)
        subject.setPos(x + 9, y + 6)
        subject.setTextWidth(_CELL_W - 18)
