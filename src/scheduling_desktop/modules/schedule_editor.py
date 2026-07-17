"""Módulo 4 · Schedule Editor: la rejilla semanal del horario con drag&drop.

Dibuja la rejilla día x período (``QGraphicsView``) del recurso en foco
(docente/grupo/aula); los conflictos se pintan en rojo. Arrastrar una clase a
otra celda pide al motor **reubicarla y reoptimizar** (``move_class``); si no
cabe, el horario no cambia. *Deshacer* revierte el último movimiento. La UI no
calcula nada del horario: todo viene de ``TimetableView`` y ``move_class``.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
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


def _cell_at(x: float, y: float) -> tuple[int, int]:
    """(día, período) de una posición de escena; negativos si cae en cabeceras."""
    return int((x - _ROWHEAD) // _CELL_W), int((y - _HEAD) // _CELL_H)


class _TimetableView(QGraphicsView):
    """Vista que traduce un arrastre de clase en una petición de mover."""

    move_requested = Signal(int, int, int)  # task_id, día, período

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self._drag_task: int | None = None
        self._from: tuple[int, int] = (-1, -1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = self.mapToScene(event.position().toPoint())
        scene = self.scene()
        self._drag_task = None
        if scene is not None:
            for item in scene.items(pos):
                data = item.data(0)
                if isinstance(data, int):
                    self._drag_task = data
                    self._from = _cell_at(pos.x(), pos.y())
                    break
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_task is not None:
            pos = self.mapToScene(event.position().toPoint())
            day, period = _cell_at(pos.x(), pos.y())
            if day >= 0 and period >= 0 and (day, period) != self._from:
                self.move_requested.emit(self._drag_task, day, period)
            self._drag_task = None
        super().mouseReleaseEvent(event)


class ScheduleEditorModule(QWidget):
    """Vista semanal del horario por docente/grupo/aula con drag&drop."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._focus = QComboBox()
        self._focus.currentIndexChanged.connect(self._redraw)

        self._undo_btn = QPushButton("Deshacer")
        self._undo_btn.clicked.connect(self._on_undo)
        self._undo_btn.setEnabled(False)
        self._hint = QLabel("Arrastra una clase a otra celda para moverla.")
        self._hint.setStyleSheet("color: #64748b;")

        top = QHBoxLayout()
        top.addWidget(QLabel("Ver por:"))
        top.addWidget(self._focus, stretch=1)
        top.addWidget(self._hint)
        top.addWidget(self._undo_btn)

        self._scene = QGraphicsScene()
        self._view = _TimetableView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.move_requested.connect(self._on_move)

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
        self._undo_btn.setEnabled(self._bridge.can_undo)
        self._redraw()

    def _on_move(self, task_id: int, day: int, period: int) -> None:
        self._bridge.move_class(task_id, day, period)  # el puente emite refresh

    def _on_undo(self) -> None:
        self._bridge.undo()

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
