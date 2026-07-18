"""Módulo 4 · Schedule Editor: la rejilla semanal del horario con drag&drop.

Dibuja la rejilla día x período (``QGraphicsView``) del recurso en foco
(docente/grupo/aula); los conflictos se pintan en rojo. Arrastrar una clase a
otra celda pide al motor **reubicarla y reoptimizar** (``move_class``); si no
cabe, el horario no cambia. *Deshacer* revierte el último movimiento. La UI no
calcula nada del horario: todo viene de ``TimetableView`` y ``move_class``.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import MoveTarget, TimetableCell, TimetableView

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
_OK = QColor(34, 197, 94, 90)  # verde: destino disponible
_NO = QColor(239, 68, 68, 70)  # rojo: destino no disponible
# mini-rejilla del mosaico (legible: con encabezados y texto)
_MW, _MH, _MHEAD, _MROWHEAD, _MGAP = 78.0, 44.0, 40.0, 30.0, 44.0


def _cell_rect(day: int, period: int, duration: int = 1) -> QRectF:
    return QRectF(_ROWHEAD + day * _CELL_W, _HEAD + period * _CELL_H, _CELL_W, duration * _CELL_H)


def _cell_center(day: int, period: int) -> QPointF:
    return QPointF(_ROWHEAD + (day + 0.5) * _CELL_W, _HEAD + (period + 0.5) * _CELL_H)


def _cell_at(x: float, y: float) -> tuple[int, int]:
    """(día, período) de una posición de escena; negativos si cae en cabeceras."""
    return int((x - _ROWHEAD) // _CELL_W), int((y - _HEAD) // _CELL_H)


class _TimetableView(QGraphicsView):
    """Vista que emite el ciclo de un arrastre de clase (inicio/mover/soltar)."""

    drag_started = Signal(int)  # task_id
    drag_moved = Signal(int, int)  # día, período
    drag_dropped = Signal(int, int)  # día, período
    cell_context = Signal(int, int)  # día, período (clic derecho)

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self._dragging = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = self.mapToScene(event.position().toPoint())
        scene = self.scene()
        task: int | None = None
        if scene is not None:
            for item in scene.items(pos):
                data = item.data(0)
                if isinstance(data, int):
                    task = data
                    break
        if task is not None:
            self._dragging = True
            self.drag_started.emit(task)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        pos = self.mapToScene(event.pos())
        day, period = _cell_at(pos.x(), pos.y())
        if day >= 0 and period >= 0:
            self.cell_context.emit(day, period)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            pos = self.mapToScene(event.position().toPoint())
            day, period = _cell_at(pos.x(), pos.y())
            self.drag_moved.emit(day, period)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._dragging = False
            pos = self.mapToScene(event.position().toPoint())
            day, period = _cell_at(pos.x(), pos.y())
            self.drag_dropped.emit(day, period)
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
        self._lunch_btn = QPushButton("Ventana de almuerzo…")
        self._lunch_btn.clicked.connect(self._edit_lunch_window)
        self._mosaic_btn = QPushButton("Mosaico de grupos")
        self._mosaic_btn.setCheckable(True)
        self._mosaic_btn.toggled.connect(self._redraw)
        self._hint = QLabel("Arrastra para mover · clic derecho para bloquear/liberar una hora.")
        self._hint.setStyleSheet("color: #64748b;")

        top = QHBoxLayout()
        top.addWidget(QLabel("Ver por:"))
        top.addWidget(self._focus, stretch=1)
        top.addWidget(self._hint)
        top.addWidget(self._mosaic_btn)
        top.addWidget(self._lunch_btn)
        top.addWidget(self._undo_btn)

        self._scene = QGraphicsScene()
        self._view = _TimetableView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.drag_started.connect(self._on_drag_started)
        self._view.drag_moved.connect(self._on_drag_moved)
        self._view.drag_dropped.connect(self._on_drag_dropped)
        self._view.cell_context.connect(self._on_cell_context)

        # Inspector lateral (vistas enlazadas: clic en clase -> docente/aula).
        self._inspector = QLabel("Haz clic en una clase para ver sus detalles.")
        self._inspector.setWordWrap(True)
        self._inspector.setStyleSheet("font-weight: 600;")
        self._btn_teacher = QPushButton("Ver horario del docente")
        self._btn_room = QPushButton("Ver horario del aula")
        self._btn_group = QPushButton("Ver horario del grupo")
        for btn in (self._btn_teacher, self._btn_room, self._btn_group):
            btn.setEnabled(False)
        self._clicked_teacher = -1
        self._clicked_room = -1
        self._clicked_group = -1
        self._btn_teacher.clicked.connect(lambda: self._focus_on(self._clicked_teacher))
        self._btn_room.clicked.connect(lambda: self._focus_on(self._clicked_room))
        self._btn_group.clicked.connect(lambda: self._focus_on(self._clicked_group))

        inspector_box = QVBoxLayout()
        inspector_box.addWidget(QLabel("Clase seleccionada"))
        inspector_box.addWidget(self._inspector)
        inspector_box.addWidget(self._btn_teacher)
        inspector_box.addWidget(self._btn_group)
        inspector_box.addWidget(self._btn_room)
        inspector_box.addStretch(1)
        inspector_widget = QWidget()
        inspector_widget.setMaximumWidth(240)
        inspector_widget.setLayout(inspector_box)

        center = QHBoxLayout()
        center.addWidget(self._view, stretch=1)
        center.addWidget(inspector_widget)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(center, stretch=1)

        # Colores de materia configurados (Datos -> Materias), como Untis.
        self._colors: dict[str, str] = {}
        # Estado del arrastre en curso.
        self._view_model: TimetableView | None = None
        self._drag_task: int | None = None
        self._drag_source: tuple[int, int] = (-1, -1)
        self._targets: dict[tuple[int, int], MoveTarget] = {}
        self._overlays: list[QGraphicsItem] = []
        self._arrow: list[QGraphicsItem] = []

        bridge.session_refreshed.connect(self.refresh)

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

    def _on_undo(self) -> None:
        self._bridge.undo()

    def _on_cell_context(self, day: int, period: int) -> None:
        focus_id = self._focus.currentData()
        if not isinstance(focus_id, int) or not self._bridge.can_block(focus_id):
            self._bridge.status_message.emit("Bloquear horas solo aplica a docentes y grupos")
            return
        menu = QMenu(self)
        blocked = (day, period) in self._bridge.blocked_hours(focus_id)
        menu.addAction(
            "Liberar esta hora" if blocked else "Bloquear esta hora",
            lambda: self._bridge.toggle_block(focus_id, day, period),
        )
        menu.exec(self.cursor().pos())

    def _edit_lunch_window(self) -> None:
        if self._view_model is None:
            return
        periods = self._view_model.periods_per_day
        current = self._bridge.lunch_window()
        dialog = QDialog(self)
        dialog.setWindowTitle("Ventana de almuerzo")
        desde = QSpinBox()
        desde.setRange(1, periods)
        desde.setValue((current.start + 1) if current else 1)
        hasta = QSpinBox()
        hasta.setRange(1, periods)
        hasta.setValue((current.end + 1) if current else min(periods, 4))
        # 'Hasta' nunca antes que 'Desde'.
        desde.valueChanged.connect(lambda v: hasta.setValue(max(hasta.value(), v)))
        info = QLabel(
            "El motor dejará al menos una hora libre en este rango cada día para almorzar."
        )
        info.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Desde el período:", desde)
        form.addRow("Hasta el período:", hasta)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Reset
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        reset = buttons.button(QDialogButtonBox.StandardButton.Reset)
        reset.setText("Quitar almuerzo")

        def _clear() -> None:
            self._bridge.clear_lunch_window()
            dialog.reject()

        reset.clicked.connect(_clear)
        box = QVBoxLayout(dialog)
        box.addWidget(info)
        box.addLayout(form)
        box.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._bridge.set_lunch_window(desde.value() - 1, hasta.value() - 1)

    # --- ciclo de arrastre (verde/rojo + flecha) ------------------------ #
    def _on_drag_started(self, task_id: int) -> None:
        self._clear_drag()
        self._drag_task = task_id
        if self._view_model is not None:
            match = next((c for c in self._view_model.cells if c.task_id == task_id), None)
            self._drag_source = (match.day, match.period) if match is not None else (-1, -1)
        self._targets = {(t.day, t.period): t for t in self._bridge.move_targets(task_id)}
        for (day, period), target in self._targets.items():
            if (day, period) == self._drag_source:
                continue
            overlay = self._scene.addRect(
                _cell_rect(day, period),
                QPen(Qt.PenStyle.NoPen),
                QBrush(_OK if target.feasible else _NO),
            )
            overlay.setZValue(5)
            self._overlays.append(overlay)

    def _on_drag_moved(self, day: int, period: int) -> None:
        for item in self._arrow:
            self._scene.removeItem(item)
        self._arrow.clear()
        if self._drag_task is None or self._drag_source == (-1, -1):
            return
        if (day, period) == self._drag_source or (day, period) not in self._targets:
            return
        feasible = self._targets[(day, period)].feasible
        self._draw_arrow(
            _cell_center(*self._drag_source), _cell_center(day, period), _OK if feasible else _NO
        )

    def _on_drag_dropped(self, day: int, period: int) -> None:
        task = self._drag_task
        source = self._drag_source
        target = self._targets.get((day, period))
        self._clear_drag()
        if task is None:
            return
        if (day, period) == source:
            self._inspect(task)  # soltar donde estaba = clic: mostrar detalles
            return
        if target is not None and target.feasible:
            self._bridge.move_class(task, day, period)  # el puente emite refresh
        elif target is not None:
            self._bridge.status_message.emit(f"No se puede mover ahí: {target.reason}")
        else:
            self._bridge.status_message.emit("Suelta la clase dentro de la rejilla")

    def _inspect(self, task_id: int) -> None:
        if self._view_model is None:
            return
        cell = next((c for c in self._view_model.cells if c.task_id == task_id), None)
        if cell is None:
            return
        self._clicked_teacher = cell.teacher_id
        self._clicked_group = cell.group_id
        self._clicked_room = cell.room_id
        self._inspector.setText(
            f"{cell.subject}\nDocente: {cell.teacher}\nGrupo: {cell.group}\nAula: {cell.room}"
        )
        self._btn_teacher.setEnabled(cell.teacher_id >= 0)
        self._btn_group.setEnabled(cell.group_id >= 0)
        self._btn_room.setEnabled(cell.room_id >= 0)

    def _focus_on(self, resource_id: int) -> None:
        if resource_id < 0:
            return
        index = self._focus.findData(resource_id)
        if index >= 0:
            self._focus.setCurrentIndex(index)  # dispara _redraw

    def _clear_drag(self) -> None:
        for item in (*self._overlays, *self._arrow):
            self._scene.removeItem(item)
        self._overlays.clear()
        self._arrow.clear()
        self._drag_task = None
        self._drag_source = (-1, -1)
        self._targets = {}

    def _draw_arrow(self, start: QPointF, end: QPointF, color: QColor) -> None:
        pen = QPen(color.darker(180))
        pen.setWidth(4)
        line = self._scene.addLine(QLineF(start, end), pen)
        line.setZValue(6)
        self._arrow.append(line)
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = 16.0
        left = QPointF(
            end.x() - size * math.cos(angle - math.pi / 6),
            end.y() - size * math.sin(angle - math.pi / 6),
        )
        right = QPointF(
            end.x() - size * math.cos(angle + math.pi / 6),
            end.y() - size * math.sin(angle + math.pi / 6),
        )
        head = self._scene.addPolygon(
            QPolygonF([end, left, right]), QPen(Qt.PenStyle.NoPen), QBrush(color.darker(180))
        )
        head.setZValue(6)
        self._arrow.append(head)

    def _redraw(self) -> None:
        self._clear_drag()
        self._scene.clear()
        if not self._bridge.has_session or self._focus.count() == 0:
            self._view_model = None
            return
        self._colors = self._bridge.subject_colors()
        mosaic = self._mosaic_btn.isChecked()
        self._focus.setEnabled(not mosaic)
        if mosaic:
            self._view_model = None
            self._draw_mosaic()
            return
        focus_id = self._focus.currentData()
        if not isinstance(focus_id, int):
            return
        view = self._bridge.timetable(focus_id)
        self._view_model = view
        self._draw_grid(view)
        self._draw_reserved(focus_id, view)
        for cell in view.cells:
            self._draw_cell(view, cell)

    def _color_for(self, subject: str) -> QColor:
        """Color de la materia: el configurado en Datos > Materias, o uno estable."""
        stored = self._colors.get(subject)
        return QColor(stored) if stored else subject_color(subject)

    def _draw_mosaic(self) -> None:
        """Horarios de varios grupos a la vez, legibles (con encabezados y materia)."""
        groups = [o for o in self._bridge.focus_options() if o.kind == "group"]
        per_row = 3
        head = QFont()
        head.setBold(True)
        for i, option in enumerate(groups):
            view = self._bridge.timetable(option.resource_id)
            col, row = i % per_row, i // per_row
            block_w = _MROWHEAD + view.days * _MW
            block_h = _MHEAD + view.periods_per_day * _MH
            bx = 14 + col * (block_w + _MGAP)
            by = 14 + row * (block_h + 26 + _MGAP)
            title = self._scene.addText(f"Grupo {option.name}", head)
            title.setDefaultTextColor(_INK)
            title.setPos(bx, by)
            ox, oy = bx, by + 26
            self._scene.addRect(
                ox, oy, block_w, _MHEAD, QPen(Qt.PenStyle.NoPen), QBrush(_HEADER_BG)
            )
            for d in range(view.days):
                lbl = self._scene.addText(day_name(d, view.days)[:2])
                lbl.setPos(ox + _MROWHEAD + d * _MW + 6, oy + 8)
            for p in range(view.periods_per_day):
                gy = oy + _MHEAD + p * _MH
                plbl = self._scene.addText(f"P{p + 1}")
                plbl.setPos(ox + 2, gy + _MH / 2 - 10)
                for d in range(view.days):
                    self._scene.addRect(ox + _MROWHEAD + d * _MW, gy, _MW, _MH, QPen(_GRID))
            for cell in view.cells:
                x = ox + _MROWHEAD + cell.day * _MW
                y = oy + _MHEAD + cell.period * _MH
                self._scene.addRect(
                    QRectF(x + 1, y + 1, _MW - 2, cell.duration * _MH - 2),
                    QPen(self._color_for(cell.subject).darker(140)),
                    QBrush(self._color_for(cell.subject)),
                )
                text = self._scene.addText("")
                text.setHtml(f"<b>{cell.subject[:8]}</b><br>{cell.room[:8]}")
                text.setDefaultTextColor(_INK)
                text.setPos(x + 4, y + 3)

    def _draw_reserved(self, focus_id: int, view: TimetableView) -> None:
        # Almuerzo (docentes): las horas LIBRES dentro de la ventana son el almuerzo.
        window = self._bridge.lunch_window()
        if window is not None and view.focus_kind == "teacher":
            occupied = {
                (cell.day, cell.period + off) for cell in view.cells for off in range(cell.duration)
            }
            lunch = QBrush(QColor(251, 146, 60, 150))
            days = window.days or tuple(range(view.days))
            hi = min(window.end + 1, view.periods_per_day)
            for day in days:
                if day >= view.days:
                    continue
                # Solo UNA hora de almuerzo por día: el primer período libre de la ventana.
                free = next((p for p in range(window.start, hi) if (day, p) not in occupied), None)
                if free is None:
                    continue
                self._scene.addRect(_cell_rect(day, free), QPen(QColor("#ea580c")), lunch)
                tag = self._scene.addText("Almuerzo")
                tag.setDefaultTextColor(QColor("#7c2d12"))
                tag.setPos(_ROWHEAD + day * _CELL_W + 10, _HEAD + free * _CELL_H + 20)
        if not self._bridge.can_block(focus_id):
            return
        hatch = QBrush(QColor(100, 116, 139, 120), Qt.BrushStyle.BDiagPattern)
        for day, period in self._bridge.blocked_hours(focus_id):
            if 0 <= day < view.days and 0 <= period < view.periods_per_day:
                self._scene.addRect(_cell_rect(day, period), QPen(QColor("#94a3b8")), hatch)

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
        fill = self._color_for(cell.subject)
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
