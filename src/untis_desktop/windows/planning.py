"""Diálogo de planificación: horario de una entidad editable con arrastrar y soltar.

Réplica del Planungsdialog de Untis (sección 8 del documento maestro):

- Cuadrícula días (columnas) x períodos (filas, con hora de reloj; recreos en
  gris) de la clase, profesor o aula en foco. Cada celda muestra materia,
  profesor/clase y aula con el color de la materia; los choques llevan borde
  rojo y las lecciones fijadas un borde oscuro y una marca en la esquina.
- A la izquierda, las sesiones sin colocar de la entidad en foco.
- Arrastrar una celda (o una sesión sin colocar) pide a la Fachada, una sola
  vez, los destinos posibles (`move_targets`) y pinta cada celda de verde
  (cabe) o rojo (no cabe, con el motivo en la ayuda emergente). Al pasar sobre
  un destino válido se calcula el cambio del número de evaluación
  (`move_delta`), de forma perezosa y con caché por arrastre: cuesta ~0,1 s en
  un colegio real y nunca se calculan todos a la vez.
- Soltar en un destino válido mueve la sesión (`move_session`, se puede
  deshacer); en uno imposible no cambia nada y se avisa en la barra de estado.
- Menú contextual: Fijar/Desfijar, Desprogramar (también F7), Intercambiar
  con... (clic en otra celda de la misma duración) y Abrir lección (también
  doble clic).

Los manejadores de ratón solo traducen eventos a métodos públicos
(`begin_drag`, `hover`, `drop_on`, `unplace`, `begin_swap`, `swap_with`...),
que son los que ejercitan las pruebas sin ratón real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import (
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QContextMenuEvent,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygon,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSplitter,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import (
    EditResult,
    MasterKind,
    PeriodRow,
    TimetableGrid,
    UntisLessonRow,
    UntisMoveTarget,
    UntisTimetableCell,
)

from ..export.html import period_minutes
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import (
    BREAK_COLOR,
    CONFLICT_COLOR,
    TARGET_NO_COLOR,
    TARGET_OK_COLOR,
    day_name,
    subject_color,
)

#: Tipo MIME del arrastre de una sesión (solo dentro de la aplicación).
MIME_SESSION = "application/x-realschool-session"

#: Roles de datos que lee el delegado.
CONFLICT_ROLE = Qt.ItemDataRole.UserRole + 1
FIXED_ROLE = Qt.ItemDataRole.UserRole + 2
DELTA_ROLE = Qt.ItemDataRole.UserRole + 3
MARK_ROLE = Qt.ItemDataRole.UserRole + 4
"""Marca de la celda: `source` (origen del arrastre o del intercambio) o `hover`."""

#: Espera antes de calcular el cambio de evaluación al pasar el ratón (ms).
HOVER_DELAY_MS = 120

#: Tipos de entidad que se pueden poner en foco.
FOCUS_KINDS: tuple[tuple[str, MasterKind], ...] = (
    ("class", MasterKind.CLASSES),
    ("teacher", MasterKind.TEACHERS),
    ("room", MasterKind.ROOMS),
)

Cell = tuple[int, int]
"""`(día, período)`."""


@dataclass(slots=True)
class DragState:
    """Arrastre en curso: la sesión, sus destinos y la caché de cambios."""

    lesson: int
    source: Cell | None
    targets: dict[Cell, UntisMoveTarget]
    deltas: dict[Cell, int | None] = field(default_factory=dict)


class PlanningDelegate(QStyledItemDelegate):
    """Pinta sobre la celda normal: choque, fijada, origen y cambio de evaluación."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        rect: QRect = option.rect
        painter.save()
        if index.data(FIXED_ROLE):
            painter.setPen(QPen(QColor("#1f2937"), 2))
            painter.drawRect(rect.adjusted(2, 2, -2, -2))
            esquina = QPolygon(
                [
                    QPoint(rect.right() - 9, rect.top() + 1),
                    QPoint(rect.right(), rect.top() + 1),
                    QPoint(rect.right(), rect.top() + 10),
                ]
            )
            painter.setBrush(QBrush(QColor("#1f2937")))
            painter.drawPolygon(esquina)
        if index.data(CONFLICT_ROLE):
            painter.setPen(QPen(QColor(CONFLICT_COLOR), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))
        marca = index.data(MARK_ROLE)
        if marca in ("source", "hover"):
            color = "#2563eb" if marca == "source" else "#111827"
            painter.setPen(QPen(QColor(color), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(3, 3, -4, -4))
        delta = index.data(DELTA_ROLE)
        if isinstance(delta, int):
            painter.setPen(QPen(QColor("#065f46" if delta <= 0 else "#991b1b")))
            painter.drawText(
                rect.adjusted(3, 2, -3, -2),
                int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight),
                f"{delta:+d}",
            )
        painter.restore()


class PlanningGrid(QTableWidget):
    """Cuadrícula del Diálogo de planificación: traduce ratón y teclado a órdenes."""

    def __init__(self, owner: PlanningWindow) -> None:
        super().__init__()
        self.owner = owner
        self._press: QPoint | None = None
        self._press_cell: Cell | None = None
        self._hover_cell: Cell | None = None
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(False)
        self.setItemDelegate(PlanningDelegate(self))
        self.setWordWrap(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.verticalHeader().setDefaultSectionSize(46)

    def cell_at(self, pos: QPoint) -> Cell | None:
        index = self.indexAt(pos)
        return self.owner.cell_of(index.row(), index.column()) if index.isValid() else None

    # --- ratón -------------------------------------------------------------- #

    def mousePressEvent(self, event: QMouseEvent) -> None:
        celda = self.cell_at(event.position().toPoint())
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.owner.swap_source is not None
            and celda is not None
        ):
            self.owner.swap_with(*celda)
            return
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self._press_cell = celda

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._press is not None
            and self._press_cell is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._press).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            celda = self._press_cell
            self._press = None
            self._press_cell = None
            principal = self.owner.primary(*celda)
            if principal is not None:
                self.owner.begin_drag(principal.lesson, celda)
                self.owner.run_drag(self)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press = None
        self._press_cell = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        celda = self.cell_at(event.position().toPoint())
        if celda is not None:
            self.owner.open_lesson(*celda)

    # --- arrastrar y soltar --------------------------------------------------- #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(MIME_SESSION) and self.owner.drag is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self.owner.drag is None:
            event.ignore()
            return
        celda = self.cell_at(event.position().toPoint())
        if celda != self._hover_cell:
            self._hover_cell = celda
            self.owner.hover_later(celda)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._hover_cell = None
        self.owner.hover_later(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._hover_cell = None
        celda = self.cell_at(event.position().toPoint())
        if celda is None or self.owner.drag is None:
            event.ignore()
            self.owner.end_drag()
            return
        resultado = self.owner.drop_on(*celda)
        if resultado.ok:
            event.acceptProposedAction()
        else:
            event.ignore()

    # --- teclado y menú -------------------------------------------------------- #

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F7:
            self.owner.unplace_current()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.owner.cancel_modes()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        celda = self.cell_at(event.pos())
        if celda is None:
            return
        menu = self.owner.context_menu(*celda)
        if menu is not None:
            menu.exec(event.globalPos())


class UnplacedList(QListWidget):
    """Sesiones sin colocar: se arrastran a la cuadrícula; se suelta aquí para desprogramar."""

    def __init__(self, owner: PlanningWindow) -> None:
        super().__init__()
        self.owner = owner
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(False)

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        item: QListWidgetItem | None = self.currentItem()
        if item is None:
            return
        leccion = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(leccion, int):
            self.owner.begin_drag(leccion, None)
            self.owner.run_drag(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        drag = self.owner.drag
        if event.mimeData().hasFormat(MIME_SESSION) and drag is not None and drag.source:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        drag = self.owner.drag
        if drag is not None and drag.source is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        drag = self.owner.drag
        if drag is None or drag.source is None:
            event.ignore()
            return
        fuente = drag.source
        self.owner.end_drag()
        if self.owner.unplace(*fuente).ok:
            event.acceptProposedAction()
        else:
            event.ignore()


class PlanningWindow(QWidget):
    """Diálogo de planificación de una clase, profesor o aula."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.focus: tuple[str, str] | None = None
        self.grid: TimetableGrid | None = None
        self.drag: DragState | None = None
        self.swap_source: tuple[int, Cell] | None = None
        self._swap_candidates: set[Cell] = set()
        self._days: tuple[int, ...] = ()
        self._periods: tuple[PeriodRow, ...] = ()
        self._lessons: dict[int, UntisLessonRow] = {}
        self._rendered: tuple[object, str | None, tuple[str, str] | None] | None = None
        self._stale = True
        self._hover: Cell | None = None
        self._pending_hover: Cell | None = None
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(HOVER_DELAY_MS)
        self._hover_timer.timeout.connect(self._hover_pending)

        # --- barra de foco -------------------------------------------------- #
        self.kind_label = QLabel()
        self.kind_combo = QComboBox()
        for clave, _master in FOCUS_KINDS:
            self.kind_combo.addItem(clave, clave)
        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumContentsLength(12)
        self.evaluation_label = QLabel()
        self.delta_label = QLabel()
        self.delta_label.setMinimumWidth(220)
        barra = QHBoxLayout()
        barra.addWidget(self.kind_label)
        barra.addWidget(self.kind_combo)
        barra.addWidget(self.entity_combo, 1)
        barra.addSpacing(12)
        barra.addWidget(self.evaluation_label)
        barra.addSpacing(12)
        barra.addWidget(self.delta_label)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self.entity_combo.currentIndexChanged.connect(self._on_entity_changed)

        # --- lista sin colocar + cuadrícula ------------------------------------- #
        self.unplaced_label = QLabel()
        self.unplaced_list = UnplacedList(self)
        izquierda = QWidget()
        capa_izq = QVBoxLayout(izquierda)
        capa_izq.setContentsMargins(0, 0, 0, 0)
        capa_izq.addWidget(self.unplaced_label)
        capa_izq.addWidget(self.unplaced_list, 1)
        self.table = PlanningGrid(self)
        division = QSplitter(Qt.Orientation.Horizontal)
        division.addWidget(izquierda)
        division.addWidget(self.table)
        division.setStretchFactor(0, 1)
        division.setStretchFactor(1, 5)

        principal = QVBoxLayout(self)
        principal.addLayout(barra)
        principal.addWidget(division, 1)

        bridge.refreshed.connect(self._on_refreshed)
        bridge.project_opened.connect(self._on_project_opened)
        bridge.selection_changed.connect(self._on_selection_changed)
        bridge.lesson_selected.connect(self._on_lesson_selected)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()
        if bridge.has_session:
            self._load_entities()
            if bridge.selection is not None:
                self._on_selection_changed(*bridge.selection)

    # --- textos ----------------------------------------------------------------- #

    def _retranslate(self) -> None:
        nombres = {
            "class": self.tr("Clase"),
            "teacher": self.tr("Profesor"),
            "room": self.tr("Aula"),
        }
        for i in range(self.kind_combo.count()):
            self.kind_combo.setItemText(i, nombres[str(self.kind_combo.itemData(i))])
        self.kind_label.setText(self.tr("Foco:"))
        self.unplaced_label.setText(self.tr("Sin colocar"))
        self.table.setHorizontalHeaderLabels(
            [day_name(d, self.bridge.language) for d in self._days]
        )
        self._update_evaluation_label()

    # --- foco -------------------------------------------------------------------- #

    def _entity_ids(self, kind: str) -> list[str]:
        maestro = dict(FOCUS_KINDS).get(kind)
        if maestro is None or not self.bridge.has_session:
            return []
        tabla = self.bridge.service.master_table(self.bridge.session, maestro)
        return [r.key for r in tabla.rows]

    def _load_entities(self) -> None:
        """Rellena el combo de entidades del tipo elegido, conservando la actual."""
        kind = str(self.kind_combo.currentData())
        actual = self.entity_combo.currentText()
        ids = self._entity_ids(kind)
        self.entity_combo.blockSignals(True)
        self.entity_combo.clear()
        self.entity_combo.addItems(ids)
        if actual in ids:
            self.entity_combo.setCurrentText(actual)
        self.entity_combo.blockSignals(False)
        if self.focus is None or self.focus[0] != kind or self.focus[1] not in ids:
            self.focus = (kind, ids[0]) if ids else None

    def set_focus(self, kind: str, entity_id: str) -> bool:
        """Pone en foco una clase, profesor o aula y la dibuja."""
        if kind not in dict(FOCUS_KINDS) or not self.bridge.has_session:
            return False
        ids = self._entity_ids(kind)
        if entity_id not in ids:
            return False
        self.kind_combo.blockSignals(True)
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(kind))
        self.kind_combo.blockSignals(False)
        self.entity_combo.blockSignals(True)
        self.entity_combo.clear()
        self.entity_combo.addItems(ids)
        self.entity_combo.setCurrentText(entity_id)
        self.entity_combo.blockSignals(False)
        if self.focus != (kind, entity_id):
            self.focus = (kind, entity_id)
            self.cancel_modes()
            self.refresh(force=True)
        self._announce_focus()
        return True

    def _on_kind_changed(self, _index: int) -> None:
        self.focus = None
        self._load_entities()
        self.cancel_modes()
        self.refresh(force=True)
        self._announce_focus()

    def _on_entity_changed(self, _index: int) -> None:
        texto = self.entity_combo.currentText()
        if not texto:
            return
        self.focus = (str(self.kind_combo.currentData()), texto)
        self.cancel_modes()
        self.refresh(force=True)
        self._announce_focus()

    def _announce_focus(self) -> None:
        if self.focus is not None:
            self.bridge.select(*self.focus)

    def _on_selection_changed(self, kind: str, entity_id: str) -> None:
        if kind in dict(FOCUS_KINDS) and self.focus != (kind, entity_id):
            self.set_focus(kind, entity_id)

    def _on_lesson_selected(self, lesson: int) -> None:
        if not self.bridge.has_session:
            return
        if self.grid is None or not self._shows_lesson(lesson):
            fila = self._lesson_rows().get(lesson)
            if fila is not None:
                clases = [
                    c.strip() for line in fila.lines for c in line.classes.split(",") if c.strip()
                ]
                profesores = [line.teacher for line in fila.lines if line.teacher]
                if clases:
                    self.set_focus("class", clases[0])
                elif profesores:
                    self.set_focus("teacher", profesores[0])
        self.highlight_lesson(lesson)

    def _shows_lesson(self, lesson: int) -> bool:
        grid = self.grid
        if grid is None:
            return False
        return any(c.lesson == lesson for c in grid.cells) or any(
            n == lesson for n, _ in grid.unplaced
        )

    def highlight_lesson(self, lesson: int) -> list[Cell]:
        """Selecciona las celdas (o la fila sin colocar) de una lección."""
        celdas: list[Cell] = []
        if self.grid is None:
            return celdas
        self.table.clearSelection()
        for c in self.grid.cells:
            if c.lesson == lesson:
                pos = self._position(c.day, c.period)
                if pos is not None:
                    celdas.append((c.day, c.period))
                    if len(celdas) == 1:
                        self.table.setCurrentCell(*pos)
        for i in range(self.unplaced_list.count()):
            item = self.unplaced_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == lesson:
                self.unplaced_list.setCurrentItem(item)
        return celdas

    # --- refresco ------------------------------------------------------------------ #

    def _on_project_opened(self) -> None:
        self.focus = None
        self._rendered = None
        self.drag = None
        self.swap_source = None
        self._load_entities()

    def _on_refreshed(self) -> None:
        if self.isVisible():
            self.refresh()
        else:
            self._stale = True

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def _lesson_rows(self) -> dict[int, UntisLessonRow]:
        if not self._lessons and self.bridge.has_session:
            self._lessons = {r.number: r for r in self.bridge.service.lessons(self.bridge.session)}
        return self._lessons

    def refresh(self, *, force: bool = False) -> None:
        """Relee el horario de la entidad en foco (si cambió algo)."""
        self._stale = False
        if not self.bridge.has_session:
            self.grid = None
            self._rendered = None
            self._fill()
            return
        s = self.bridge.session
        if self.focus is None:
            self._load_entities()
        clave = (s.project, s.active_timetable, self.focus)
        previo = self._rendered
        if not force and previo is not None and previo[0] is s.project and previo[1:] == clave[1:]:
            return
        if self._rendered is None or self._rendered[0] is not s.project:
            self._lessons = {}
            self.cancel_modes()
        self._rendered = clave
        self.grid = (
            self.bridge.service.timetable_grid(s, *self.focus) if self.focus is not None else None
        )
        self._fill()

    def _fill(self) -> None:
        grid = self.grid
        self._days = grid.days if grid is not None else ()
        self._periods = grid.periods if grid is not None else ()
        tabla = self.table
        tabla.clear()
        tabla.setColumnCount(len(self._days))
        tabla.setRowCount(len(self._periods))
        tabla.setHorizontalHeaderLabels([day_name(d, self.bridge.language) for d in self._days])
        tabla.setVerticalHeaderLabels([f"{p.number}\n{p.start}-{p.end}" for p in self._periods])
        for fila, periodo in enumerate(self._periods):
            if periodo.is_break:
                tabla.setRowHeight(fila, 16)
            else:
                tabla.setRowHeight(fila, 46)
            for col in range(len(self._days)):
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                tabla.setItem(fila, col, item)
        self._paint_all()
        self._fill_unplaced()
        self._update_evaluation_label()

    def _fill_unplaced(self) -> None:
        self.unplaced_list.clear()
        if self.grid is None:
            return
        filas = self._lesson_rows()
        for leccion, falta in self.grid.unplaced:
            fila = filas.get(leccion)
            materia = ", ".join(dict.fromkeys(li.subject for li in fila.lines)) if fila else ""
            profes = ", ".join(dict.fromkeys(li.teacher for li in fila.lines)) if fila else ""
            texto = self.tr("{0} {1} {2}: {3} sin colocar").format(leccion, materia, profes, falta)
            item = QListWidgetItem(" ".join(texto.split()))
            item.setData(Qt.ItemDataRole.UserRole, leccion)
            item.setData(Qt.ItemDataRole.UserRole + 1, falta)
            if fila is not None and fila.lines:
                item.setBackground(QBrush(subject_color(fila.lines[0].subject)))
            self.unplaced_list.addItem(item)

    def _update_evaluation_label(self) -> None:
        if not self.bridge.has_session:
            self.evaluation_label.setText("")
            return
        ev = self.bridge.service.evaluation(self.bridge.session)
        if ev is None:
            self.evaluation_label.setText(self.tr("Sin horario activo"))
        else:
            self.evaluation_label.setText(
                self.tr("Evaluación: {0} ({1} sin colocar, {2} choques)").format(
                    ev.total, ev.unplaced_periods, ev.clashes
                )
            )

    # --- geometría ------------------------------------------------------------------ #

    def cell_of(self, row: int, column: int) -> Cell | None:
        """`(día, período)` de una celda de la tabla (`None` en recreos o fuera)."""
        if not (0 <= row < len(self._periods) and 0 <= column < len(self._days)):
            return None
        periodo = self._periods[row]
        if periodo.is_break:
            return None
        return (self._days[column], periodo.number)

    def _position(self, day: int, period: int) -> tuple[int, int] | None:
        try:
            col = self._days.index(day)
        except ValueError:
            return None
        for fila, p in enumerate(self._periods):
            if p.number == period:
                return (fila, col)
        return None

    def item_at(self, day: int, period: int) -> QTableWidgetItem | None:
        pos = self._position(day, period)
        return self.table.item(*pos) if pos is not None else None

    def cells_at(self, day: int, period: int) -> tuple[UntisTimetableCell, ...]:
        return self.grid.at(day, period) if self.grid is not None else ()

    def primary(self, day: int, period: int) -> UntisTimetableCell | None:
        celdas = self.cells_at(day, period)
        return celdas[0] if celdas else None

    def current_cell(self) -> Cell | None:
        return self.cell_of(self.table.currentRow(), self.table.currentColumn())

    def select_cell(self, day: int, period: int) -> None:
        pos = self._position(day, period)
        if pos is not None:
            self.table.setCurrentCell(*pos)

    def cell_color(self, day: int, period: int) -> QColor:
        """Color de fondo con el que se ve la celda ahora mismo."""
        item = self.item_at(day, period)
        return item.background().color() if item is not None else QColor()

    def cell_text(self, day: int, period: int) -> str:
        item = self.item_at(day, period)
        return item.text() if item is not None else ""

    def _period_duration(self, period: int) -> int:
        return next((period_minutes(p) for p in self._periods if p.number == period), 0)

    # --- pintura --------------------------------------------------------------------- #

    def _text_for(self, celdas: tuple[UntisTimetableCell, ...]) -> str:
        kind = self.focus[0] if self.focus is not None else "class"
        partes: list[str] = []
        for c in celdas:
            if kind == "class":
                otros = ", ".join(c.teachers)
            elif kind == "teacher":
                otros = ", ".join(c.classes)
            else:
                otros = ", ".join((*c.classes, *c.teachers))
            aulas = ", ".join(c.rooms)
            partes.append("\n".join(x for x in (c.subject, otros, aulas) if x))
        return "\n/ ".join(partes)

    def _paint_all(self) -> None:
        for fila in range(len(self._periods)):
            for col in range(len(self._days)):
                self._paint(fila, col)

    def _paint(self, row: int, col: int) -> None:
        item = self.table.item(row, col)
        if item is None:
            return
        periodo = self._periods[row]
        dia = self._days[col]
        if periodo.is_break:
            item.setBackground(QBrush(QColor(BREAK_COLOR)))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            return
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        celdas = self.cells_at(dia, periodo.number)
        item.setText(self._text_for(celdas))
        ayuda = [
            self.tr("Lección {0}").format(c.lesson)
            + (self.tr(" (fijada)") if c.fixed else "")
            + (self.tr(" - choque") if c.conflict else "")
            for c in celdas
        ]
        fondo = subject_color(celdas[0].subject, celdas[0].color) if celdas else QColor("#ffffff")
        item.setData(CONFLICT_ROLE, any(c.conflict for c in celdas))
        item.setData(FIXED_ROLE, any(c.fixed for c in celdas))
        item.setData(DELTA_ROLE, None)
        marca = ""
        celda = (dia, periodo.number)
        drag = self.drag
        if drag is not None:
            if celda == drag.source:
                marca = "source"
            objetivo = drag.targets.get(celda)
            if objetivo is not None:
                fondo = QColor(TARGET_OK_COLOR if objetivo.feasible else TARGET_NO_COLOR)
                if objetivo.feasible:
                    delta = drag.deltas.get(celda)
                    if delta is not None:
                        item.setData(DELTA_ROLE, delta)
                        ayuda.append(self.tr("Cambio de evaluación: {0:+d}").format(delta))
                    else:
                        ayuda.append(self.tr("Destino posible"))
                else:
                    ayuda.append(self.tr("No cabe: {0}").format(objetivo.reason))
            if celda == self._hover and marca != "source":
                marca = "hover"
        elif self.swap_source is not None:
            if celda == self.swap_source[1]:
                marca = "source"
            elif celda in self._swap_candidates:
                fondo = QColor(TARGET_OK_COLOR)
                ayuda.append(self.tr("Clic para intercambiar"))
        item.setData(MARK_ROLE, marca)
        item.setBackground(QBrush(fondo))
        item.setToolTip("\n".join(ayuda))

    def _paint_cell(self, cell: Cell | None) -> None:
        if cell is None:
            return
        pos = self._position(*cell)
        if pos is not None:
            self._paint(*pos)

    # --- arrastrar y soltar -------------------------------------------------------------- #

    def begin_drag(self, lesson: int, cell: Cell | None) -> tuple[UntisMoveTarget, ...]:
        """Empieza a arrastrar una sesión: pide (una vez) los destinos y los pinta."""
        self.cancel_modes()
        if not self.bridge.has_session:
            return ()
        objetivos = self.bridge.service.move_targets(self.bridge.session, lesson, cell)
        self.drag = DragState(lesson, cell, {(t.day, t.period): t for t in objetivos})
        self._paint_all()
        posibles = sum(1 for t in objetivos if t.feasible)
        self.delta_label.setText(
            self.tr("Lección {0}: {1} destino(s) posible(s)").format(lesson, posibles)
        )
        return objetivos

    def targets(self) -> dict[Cell, UntisMoveTarget]:
        """Destinos del arrastre en curso (vacío si no se arrastra)."""
        return dict(self.drag.targets) if self.drag is not None else {}

    def hover(self, day: int, period: int) -> int | None:
        """El ratón pasa sobre una celda durante el arrastre: cambio de evaluación.

        Solo se calcula para destinos posibles y una vez por celda y arrastre.
        """
        drag = self.drag
        if drag is None:
            return None
        anterior = self._hover
        self._hover = (day, period)
        self._paint_cell(anterior)
        objetivo = drag.targets.get((day, period))
        if objetivo is None or not objetivo.feasible:
            motivo = objetivo.reason if objetivo is not None else self.tr("fuera de la rejilla")
            self.delta_label.setText(self.tr("No cabe: {0}").format(motivo))
            self._paint_cell(self._hover)
            return None
        if (day, period) not in drag.deltas:
            drag.deltas[(day, period)] = self.bridge.service.move_delta(
                self.bridge.session, drag.lesson, drag.source, (day, period)
            )
        delta = drag.deltas[(day, period)]
        if delta is None:
            self.delta_label.setText(self.tr("Destino posible"))
        else:
            self.delta_label.setText(self.tr("Cambio de evaluación: {0:+d}").format(delta))
        self._paint_cell(self._hover)
        return delta

    def hover_later(self, cell: Cell | None) -> None:
        """Programa `hover` tras una espera corta (el ratón puede seguir de largo)."""
        self._pending_hover = cell
        if cell is None:
            self._hover_timer.stop()
            anterior = self._hover
            self._hover = None
            self._paint_cell(anterior)
        else:
            self._hover_timer.start()

    def _hover_pending(self) -> None:
        if self._pending_hover is not None:
            self.hover(*self._pending_hover)

    def drop_on(self, day: int, period: int) -> EditResult:
        """Suelta la sesión arrastrada en una celda."""
        drag = self.drag
        if drag is None:
            return EditResult.failure(self.tr("No se está arrastrando nada"))
        self.end_drag()
        destino = (day, period)
        if destino == drag.source:
            return EditResult.success()
        objetivo = drag.targets.get(destino)
        if objetivo is None:
            mensaje = self.tr("Esa celda no es un destino de la sesión")
            self.bridge.status.emit(mensaje)
            return EditResult.failure(mensaje)
        if not objetivo.feasible:
            mensaje = self.tr("No cabe: {0}").format(objetivo.reason)
            self.bridge.status.emit(mensaje)
            return EditResult.failure(mensaje)
        s = self.bridge.session
        resultado = self.bridge.edit(
            lambda: self.bridge.service.move_session(s, drag.lesson, drag.source, destino)
        )
        if resultado.ok:
            self.refresh()
            self.select_cell(day, period)
        return resultado

    def end_drag(self) -> None:
        """Termina el arrastre y quita los colores de destino."""
        self._hover_timer.stop()
        self._hover = None
        self._pending_hover = None
        if self.drag is not None:
            self.drag = None
            self._paint_all()

    def run_drag(self, source: QWidget) -> None:
        """Arrastre real con `QDrag` (bucle de eventos propio de Qt)."""
        if self.drag is None:
            return
        mime = QMimeData()
        mime.setData(MIME_SESSION, str(self.drag.lesson).encode("ascii"))
        arrastre = QDrag(source)
        arrastre.setMimeData(mime)
        arrastre.exec(Qt.DropAction.MoveAction)
        self.end_drag()

    def cancel_modes(self) -> None:
        """Cancela el arrastre o el intercambio en curso (Esc)."""
        swap = self.swap_source is not None
        self.swap_source = None
        self._swap_candidates = set()
        if self.drag is not None:
            self.end_drag()
        elif swap:
            self._paint_all()

    # --- órdenes de celda ----------------------------------------------------------------- #

    def unplace(self, day: int, period: int) -> EditResult:
        """Desprograma la sesión de una celda (F7)."""
        celda = self.primary(day, period)
        if celda is None:
            return EditResult.failure(self.tr("La celda está vacía"))
        s = self.bridge.session
        resultado = self.bridge.edit(
            lambda: self.bridge.service.unplace_session(s, celda.lesson, (day, period))
        )
        if resultado.ok:
            self.refresh()
        return resultado

    def unplace_current(self) -> EditResult:
        celda = self.current_cell()
        if celda is None:
            return EditResult.failure(self.tr("Elige una celda"))
        return self.unplace(*celda)

    def toggle_fixed(self, day: int, period: int) -> EditResult:
        """Fija o desfija la lección de una celda."""
        celda = self.primary(day, period)
        if celda is None:
            return EditResult.failure(self.tr("La celda está vacía"))
        s = self.bridge.session
        resultado = self.bridge.edit(
            lambda: self.bridge.service.set_fixed(s, celda.lesson, not celda.fixed)
        )
        if resultado.ok:
            self.refresh()
        return resultado

    def open_lesson(self, day: int, period: int) -> None:
        celda = self.primary(day, period)
        if celda is not None:
            self.bridge.select_lesson(celda.lesson)

    def swap_candidates(self, day: int, period: int) -> set[Cell]:
        """Celdas ocupadas por otra lección con la misma duración."""
        origen = self.primary(day, period)
        if origen is None or self.grid is None:
            return set()
        duracion = self._period_duration(period)
        return {
            (c.day, c.period)
            for c in self.grid.cells
            if c.lesson != origen.lesson
            and (c.day, c.period) != (day, period)
            and self._period_duration(c.period) == duracion
        }

    def begin_swap(self, day: int, period: int) -> set[Cell]:
        """Intercambiar con...: marca la celda origen y pinta las candidatas."""
        self.cancel_modes()
        origen = self.primary(day, period)
        if origen is None:
            return set()
        self.swap_source = (origen.lesson, (day, period))
        self._swap_candidates = self.swap_candidates(day, period)
        self._paint_all()
        self.delta_label.setText(self.tr("Elige la celda con la que intercambiar (Esc cancela)"))
        return set(self._swap_candidates)

    def swap_with(self, day: int, period: int) -> EditResult:
        """Completa el intercambio con la sesión de otra celda."""
        origen = self.swap_source
        self.cancel_modes()
        self.delta_label.clear()
        destino = self.primary(day, period)
        if origen is None or destino is None:
            return EditResult.failure(self.tr("Elige una celda ocupada"))
        if destino.lesson == origen[0]:
            return EditResult.failure(self.tr("Es la misma lección"))
        s = self.bridge.session
        resultado = self.bridge.edit(
            lambda: self.bridge.service.swap_sessions(s, origen, (destino.lesson, (day, period)))
        )
        if resultado.ok:
            self.refresh()
        return resultado

    def context_menu(self, day: int, period: int) -> QMenu | None:
        """Menú contextual de una celda ocupada."""
        celda = self.primary(day, period)
        if celda is None:
            return None
        self.select_cell(day, period)
        menu = QMenu(self)
        fijar = QAction(self.tr("Desfijar") if celda.fixed else self.tr("Fijar"), menu)
        fijar.triggered.connect(lambda _c=False: self.toggle_fixed(day, period))
        desprogramar = QAction(self.tr("Desprogramar (F7)"), menu)
        desprogramar.triggered.connect(lambda _c=False: self.unplace(day, period))
        intercambiar = QAction(self.tr("Intercambiar con..."), menu)
        intercambiar.triggered.connect(lambda _c=False: self.begin_swap(day, period))
        intercambiar.setEnabled(bool(self.swap_candidates(day, period)))
        abrir = QAction(self.tr("Abrir lección {0}").format(celda.lesson), menu)
        abrir.triggered.connect(lambda _c=False: self.open_lesson(day, period))
        for accion in (fijar, desprogramar, intercambiar):
            menu.addAction(accion)
        menu.addSeparator()
        menu.addAction(abrir)
        return menu

    # --- lista sin colocar ---------------------------------------------------------------- #

    def unplaced_lessons(self) -> list[tuple[int, int]]:
        """`(lección, períodos sin colocar)` tal como los muestra la lista."""
        salida: list[tuple[int, int]] = []
        for i in range(self.unplaced_list.count()):
            item = self.unplaced_list.item(i)
            salida.append(
                (
                    int(item.data(Qt.ItemDataRole.UserRole)),
                    int(item.data(Qt.ItemDataRole.UserRole + 1)),
                )
            )
        return salida


register(
    WindowSpec(
        key="planning",
        title="Diálogo de planificación",
        title_de="Planungsdialog",
        tab=RibbonTab.TIMETABLES,
        factory=lambda bridge: PlanningWindow(bridge),
        order=4,
    )
)
