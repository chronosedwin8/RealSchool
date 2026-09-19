"""Horario de una entidad en ventana hija propia, con su lista Sin colocar.

Como en Untis, el coordinador tiene varias ventanas pequeñas y flotantes a la
vez (el horario de la clase K2D, el del profesor ALMANZAK, el del aula P 21) y
puede sacar una hora del horario para aparcarla al lado y volver a colocarla
más tarde. Esta ventana es una de esas: un solo horario y, a su izquierda, la
lista Sin colocar donde esperan las horas aparcadas.

- Arrastrar una clase de una hora a otra la mueve: mientras se arrastra, las
  celdas donde cabe salen en verde y las imposibles en rojo con el motivo en la
  ayuda emergente, y al pasar por encima se ve el cambio de evaluación.
- Arrastrar una clase fuera del horario, a la lista Sin colocar, la desprograma
  (queda ahí esperando); arrastrarla de la lista a una hora la coloca si cabe.
- Menú contextual sobre la celda: Fijar/Desfijar, Desprogramar (también F7) y
  Abrir lección (también doble clic).
- Todo pasa por `bridge.edit`, así que Ctrl+Z deshace cualquiera de esas
  acciones y el resto de ventanas se entera.

La máquina de arrastre es la misma del Diálogo de planificación y de la ventana
Horarios (`widgets/timetable_drag.py`): aquí solo se traducen los eventos de
ratón y teclado a métodos públicos (`begin_drag`, `hover`, `drop_on`,
`unplace`...), que son los que ejercitan las pruebas sin ratón real.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import (
    EditResult,
    PeriodRow,
    TimetableGrid,
    UntisLessonRow,
    UntisMoveTarget,
    UntisTimetableCell,
)

from ..qt_bridge import FacadeBridge
from ..theme import BREAK_COLOR, day_name, subject_color, text_color_for
from ..widgets.timetable_cells import (
    BLOCKED_ROLE,
    CONFLICT_ROLE,
    DELTA_ROLE,
    FIXED_ROLE,
    MARK_ROLE,
    TimetableCellDelegate,
    cell_tooltip,
    legend_items,
    readable_colors,
)
from ..widgets.timetable_drag import (
    MIME_SESSION,
    Cell,
    DragState,
    MoveDragController,
    MoveDragTable,
)
from ..widgets.uikit import Banner, Legend, icon_label, make_action, set_texts

#: Icono de cada tipo de horario (el de la ventana hija y el de su cabecera).
KIND_ICONS: dict[str, str] = {
    "class": "classes",
    "teacher": "teachers",
    "room": "rooms",
    "subject": "subjects",
}

#: Ancho máximo de la lista Sin colocar (la ventana es pequeña).
PARKING_WIDTH = 220


class ParkingList(QListWidget):
    """Lista Sin colocar: se arrastra de aquí al horario y del horario aquí.

    Es la misma idea que la lista del Diálogo de planificación, pero esta
    ventana es independiente y no comparte estado con aquella.
    """

    def __init__(self, owner: TimetableWindow) -> None:
        super().__init__()
        self.owner = owner
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(False)
        self.setMaximumWidth(PARKING_WIDTH)

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        """Empieza a arrastrar una hora aparcada hacia el horario."""
        item: QListWidgetItem | None = self.currentItem()
        if item is None:
            return
        leccion = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(leccion, int):
            self.owner.begin_drag(leccion, None)
            self.owner.run_drag(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        arrastre = self.owner.drag
        if event.mimeData().hasFormat(MIME_SESSION) and arrastre is not None and arrastre.source:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        arrastre = self.owner.drag
        if arrastre is not None and arrastre.source is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Soltar aquí una clase del horario la saca de su hora y la aparca."""
        arrastre = self.owner.drag
        if arrastre is None or arrastre.source is None:
            event.ignore()
            return
        origen = arrastre.source
        self.owner.end_drag()
        if self.owner.unplace(*origen).ok:
            event.acceptProposedAction()
        else:
            event.ignore()


class WindowGrid(MoveDragTable):
    """Cuadrícula de la ventana hija: traduce ratón y teclado a órdenes."""

    def __init__(self, owner: TimetableWindow) -> None:
        super().__init__()
        self.owner = owner
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setItemDelegate(TimetableCellDelegate(self))
        self.setWordWrap(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.verticalHeader().setDefaultSectionSize(40)

    def start_drag(self, cell: Cell) -> bool:
        principal = self.owner.primary(*cell)
        if principal is None or not self.owner.begin_drag(principal.lesson, cell):
            return False
        self.owner.run_drag(self)
        return True

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        celda = self.cell_at(event.position().toPoint())
        if celda is not None:
            self.owner.open_lesson(*celda)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F7:
            self.owner.unplace_current()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.owner.end_drag()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        celda = self.cell_at(event.pos())
        if celda is None:
            return
        menu = self.owner.context_menu(*celda)
        if menu is not None:
            menu.exec(event.globalPos())


class TimetableWindow(QWidget):
    """Horario de una clase, profesor, aula o materia, con su lista Sin colocar."""

    title_changed = Signal(str)
    """El título de la ventana cambió (la ventana principal renombra la hija)."""

    def __init__(self, bridge: FacadeBridge, kind: str, entity_id: str) -> None:
        super().__init__()
        self.bridge = bridge
        self.kind = kind
        self.entity_id = entity_id
        self.grid: TimetableGrid | None = None
        self.shown_timetable: str | None = None
        """Horario con el que se dibujó: si no es el activo, no se arrastra."""
        self._days: tuple[int, ...] = ()
        self._periods: tuple[PeriodRow, ...] = ()
        self._lessons: dict[int, UntisLessonRow] = {}
        self._rendered: tuple[object, str | None] | None = None
        self._stale = True

        # --- cabecera ------------------------------------------------------- #
        self.kind_icon = icon_label(KIND_ICONS.get(kind, "timetables"))
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: 600;")
        self.message_label = QLabel()
        self.message_label.setStyleSheet("color: #4b5563;")
        cabecera = QHBoxLayout()
        cabecera.setSpacing(6)
        cabecera.addWidget(self.kind_icon)
        cabecera.addWidget(self.title_label, 1)
        cabecera.addWidget(self.message_label)

        # --- lista Sin colocar + cuadrícula ---------------------------------- #
        self.parking_label = QLabel()
        self.parking_list = ParkingList(self)
        self.parking_empty = QLabel()
        self.parking_empty.setWordWrap(True)
        self.parking_empty.setStyleSheet("color: #4b5563;")
        izquierda = QWidget()
        capa_izq = QVBoxLayout(izquierda)
        capa_izq.setContentsMargins(0, 0, 0, 0)
        titulo_izq = QHBoxLayout()
        titulo_izq.addWidget(icon_label("unplace"))
        titulo_izq.addWidget(self.parking_label, 1)
        capa_izq.addLayout(titulo_izq)
        capa_izq.addWidget(self.parking_list, 1)
        capa_izq.addWidget(self.parking_empty)

        self.table = WindowGrid(self)
        self.dragger = MoveDragController(
            self.table,
            bridge,
            self.cell_of,
            self.position_of,
            repaint=self.repaint_cells,
            lesson_at=self.lesson_at,
            message=self.message_label.setText,
            after_move=self._after_move,
            shown_timetable=lambda: self.shown_timetable,
        )
        self.table.dragger = self.dragger

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(izquierda)
        self.splitter.addWidget(self.table)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 4)

        self.legend = Legend()
        self.hint = Banner("tip")
        principal = QVBoxLayout(self)
        principal.setContentsMargins(6, 6, 6, 6)
        principal.addLayout(cabecera)
        principal.addWidget(self.splitter, 1)
        principal.addWidget(self.legend)
        principal.addWidget(self.hint)

        bridge.refreshed.connect(self._on_refreshed)
        bridge.project_opened.connect(self._on_project_opened)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()
        self.refresh(force=True)

    # --- textos --------------------------------------------------------------- #

    def kind_name(self) -> str:
        """Nombre del tipo de horario en el idioma activo."""
        nombres = {
            "class": self.tr("Clase"),
            "teacher": self.tr("Profesor"),
            "room": self.tr("Aula"),
            "subject": self.tr("Materia"),
        }
        return nombres.get(self.kind, self.tr("Horario"))

    def window_title(self) -> str:
        """Título de la ventana hija: «K2D - Clase 001»."""
        if self.grid is not None and self.grid.title:
            return self.grid.title
        return f"{self.kind_name()}: {self.entity_id}"

    def _retranslate(self) -> None:
        self.kind_icon.setToolTip(self.kind_name())
        self.parking_label.setText(self.tr("Sin colocar"))
        self.parking_list.setToolTip(
            self.tr(
                "Horas aparcadas: arrástralas al horario para colocarlas; suelta aquí una "
                "clase del horario para sacarla de su hora"
            )
        )
        self.parking_empty.setText(self.tr("Todo colocado."))
        self.legend.set_items(legend_items(targets=True))
        self.hint.setText(
            self.tr(
                "Arrastra una clase a otra hora, o suéltala en Sin colocar para aparcarla "
                "y colocarla después. F7 la desprograma y Ctrl+Z deshace."
            )
        )
        self.title_label.setText(self.window_title())
        self.title_label.setToolTip(
            self.tr("Horario de {0} ({1})").format(self.entity_id, self.kind_name())
        )
        if self._days:
            self.table.setHorizontalHeaderLabels(
                [day_name(d, self.bridge.language) for d in self._days]
            )
        self.title_changed.emit(self.window_title())

    # --- refresco ------------------------------------------------------------- #

    def _on_project_opened(self) -> None:
        self._lessons = {}
        self._rendered = None
        self.dragger.reset()
        self.refresh(force=True)

    def _on_refreshed(self) -> None:
        if self.isVisible():
            self.refresh()
        else:
            self._stale = True

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def refresh(self, *, force: bool = False) -> None:
        """Relee el horario de la entidad (si cambió algo) y lo pinta."""
        self._stale = False
        if not self.bridge.has_session:
            self.grid = None
            self.shown_timetable = None
            self._rendered = None
            self._fill()
            return
        s = self.bridge.session
        clave = (s.project, s.active_timetable)
        previo = self._rendered
        if not force and previo is not None and previo[0] is s.project and previo[1] == clave[1]:
            return
        if previo is None or previo[0] is not s.project:
            self._lessons = {}
        self._rendered = clave
        self.shown_timetable = s.active_timetable or None
        self.grid = self.bridge.service.timetable_grid(s, self.kind, self.entity_id)
        self._fill()

    def _lesson_rows(self) -> dict[int, UntisLessonRow]:
        if not self._lessons and self.bridge.has_session:
            self._lessons = {r.number: r for r in self.bridge.service.lessons(self.bridge.session)}
        return self._lessons

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
            tabla.setRowHeight(fila, 14 if periodo.is_break else 40)
            for col in range(len(self._days)):
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                tabla.setItem(fila, col, item)
        self.repaint_cells(None)
        self._fill_parking()
        self.title_label.setText(self.window_title())
        self.title_changed.emit(self.window_title())

    def _fill_parking(self) -> None:
        """Rehace la lista Sin colocar con las horas que le faltan a la entidad."""
        self.parking_list.clear()
        if self.grid is not None:
            filas = self._lesson_rows()
            for leccion, falta in self.grid.unplaced:
                fila = filas.get(leccion)
                materia = ", ".join(dict.fromkeys(li.subject for li in fila.lines)) if fila else ""
                profes = ", ".join(dict.fromkeys(li.teacher for li in fila.lines)) if fila else ""
                texto = self.tr("{0} {1} {2}: {3} sin colocar").format(
                    leccion, materia, profes, falta
                )
                item = QListWidgetItem(" ".join(texto.split()))
                item.setData(Qt.ItemDataRole.UserRole, leccion)
                item.setData(Qt.ItemDataRole.UserRole + 1, falta)
                if fila is not None and fila.lines:
                    fondo = subject_color(fila.lines[0].subject)
                    item.setBackground(QBrush(fondo))
                    item.setForeground(QBrush(text_color_for(fondo)))
                item.setToolTip(
                    self.tr(
                        "Lección {0}: {1} período(s) aparcado(s). Arrástrala a una hora del "
                        "horario para colocarla."
                    ).format(leccion, falta)
                )
                self.parking_list.addItem(item)
        self.parking_empty.setVisible(self.parking_list.count() == 0)

    def unplaced_lessons(self) -> list[tuple[int, int]]:
        """`(lección, períodos aparcados)` tal como los muestra la lista."""
        salida: list[tuple[int, int]] = []
        for i in range(self.parking_list.count()):
            item = self.parking_list.item(i)
            salida.append(
                (
                    int(item.data(Qt.ItemDataRole.UserRole)),
                    int(item.data(Qt.ItemDataRole.UserRole + 1)),
                )
            )
        return salida

    # --- geometría -------------------------------------------------------------- #

    def cell_of(self, row: int, column: int) -> Cell | None:
        """`(día, período)` de una celda de la tabla (`None` en recreos o fuera)."""
        if not (0 <= row < len(self._periods) and 0 <= column < len(self._days)):
            return None
        periodo = self._periods[row]
        return None if periodo.is_break else (self._days[column], periodo.number)

    def position_of(self, day: int, period: int) -> tuple[int, int] | None:
        """`(fila, columna)` de la celda `(día, período)`."""
        if day not in self._days:
            return None
        fila = next((i for i, p in enumerate(self._periods) if p.number == period), None)
        return None if fila is None else (fila, self._days.index(day))

    def item_at(self, day: int, period: int) -> QTableWidgetItem | None:
        pos = self.position_of(day, period)
        return self.table.item(*pos) if pos is not None else None

    def cells_at(self, day: int, period: int) -> tuple[UntisTimetableCell, ...]:
        return self.grid.at(day, period) if self.grid is not None else ()

    def primary(self, day: int, period: int) -> UntisTimetableCell | None:
        celdas = self.cells_at(day, period)
        return celdas[0] if celdas else None

    def lesson_at(self, day: int, period: int) -> int | None:
        """Lección de la celda `(día, período)` (la primera si hay varias)."""
        celda = self.primary(day, period)
        return celda.lesson if celda is not None else None

    def current_cell(self) -> Cell | None:
        return self.cell_of(self.table.currentRow(), self.table.currentColumn())

    def select_cell(self, day: int, period: int) -> None:
        pos = self.position_of(day, period)
        if pos is not None:
            self.table.setCurrentCell(*pos)

    def cell_text(self, day: int, period: int) -> str:
        item = self.item_at(day, period)
        return item.text() if item is not None else ""

    def cell_color(self, day: int, period: int) -> QColor:
        """Color de fondo con el que se ve la celda ahora mismo."""
        item = self.item_at(day, period)
        return item.background().color() if item is not None else QColor()

    # --- pintura ------------------------------------------------------------------ #

    def _text_for(self, cells: tuple[UntisTimetableCell, ...]) -> str:
        partes: list[str] = []
        for c in cells:
            if self.kind == "class":
                otros = ", ".join(c.teachers)
            elif self.kind == "teacher":
                otros = ", ".join(c.classes)
            else:
                otros = ", ".join((*c.classes, *c.teachers))
            partes.append("\n".join(x for x in (c.subject, otros, ", ".join(c.rooms)) if x))
        return "\n/ ".join(partes)

    def repaint_cells(self, cell: Cell | None) -> None:
        """Repinta una celda, o toda la cuadrícula si no se dice cuál."""
        if cell is None:
            for fila in range(len(self._periods)):
                for col in range(len(self._days)):
                    self._paint(fila, col)
            return
        pos = self.position_of(*cell)
        if pos is not None:
            self._paint(*pos)

    def _paint(self, row: int, col: int) -> None:
        item = self.table.item(row, col)
        if item is None:
            return
        periodo = self._periods[row]
        dia = self._days[col]
        if periodo.is_break:
            item.setBackground(QBrush(QColor(BREAK_COLOR)))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setToolTip(self.tr("Recreo"))
            return
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        celdas = self.cells_at(dia, periodo.number)
        item.setText(self._text_for(celdas))
        ayuda = [cell_tooltip(celdas)] if celdas else [self.tr("Hueco libre")]
        fondo, _texto = readable_colors(celdas)
        cerrada = self.grid is not None and self.grid.is_blocked(dia, periodo.number)
        item.setData(BLOCKED_ROLE, cerrada)
        if cerrada:
            ayuda.append(self.tr("Hora cerrada (-3): aquí no puede haber clase"))
        item.setData(CONFLICT_ROLE, any(c.conflict for c in celdas))
        item.setData(FIXED_ROLE, any(c.fixed for c in celdas))
        item.setData(DELTA_ROLE, None)
        fondo, marca = self.dragger.decorate(item, (dia, periodo.number), fondo, ayuda)
        item.setData(MARK_ROLE, marca)
        item.setBackground(QBrush(fondo))
        item.setForeground(QBrush(text_color_for(fondo)))
        item.setToolTip("\n".join(x for x in ayuda if x))

    # --- arrastrar y soltar ---------------------------------------------------------- #
    #
    # La máquina de arrastre es `MoveDragController`, la misma del Diálogo de
    # planificación y de la ventana Horarios. Aquí quedan los métodos públicos
    # que llaman los manejadores de ratón y que ejercitan las pruebas.

    @property
    def drag(self) -> DragState | None:
        """Arrastre en curso (`None` si no se está arrastrando nada)."""
        return self.dragger.state

    def begin_drag(self, lesson: int, cell: Cell | None) -> tuple[UntisMoveTarget, ...]:
        """Empieza a arrastrar una sesión: destinos posibles e imposibles, pintados."""
        return self.dragger.begin(lesson, cell)

    def targets(self) -> dict[Cell, UntisMoveTarget]:
        """Destinos del arrastre en curso (vacío si no se arrastra)."""
        return self.dragger.targets()

    def hover(self, day: int, period: int) -> int | None:
        """Pasa por encima de una celda: cambio del número de evaluación."""
        return self.dragger.hover(day, period)

    def drop_on(self, day: int, period: int) -> EditResult:
        """Suelta la sesión arrastrada en una celda."""
        return self.dragger.drop_on(day, period)

    def end_drag(self) -> None:
        """Cancela el arrastre y deja el horario como estaba (Esc)."""
        self.dragger.end()

    def run_drag(self, source: QWidget) -> None:
        """Arrastre real con `QDrag` (bucle de eventos propio de Qt)."""
        self.dragger.run(source)

    def _after_move(self, cell: Cell) -> None:
        self.refresh()
        self.select_cell(*cell)

    # --- órdenes de celda -------------------------------------------------------------- #

    def unplace(self, day: int, period: int) -> EditResult:
        """Saca la clase de su hora y la aparca en Sin colocar (F7)."""
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
        """Muestra la lección de la celda en la ventana Lecciones."""
        celda = self.primary(day, period)
        if celda is not None:
            self.bridge.select_lesson(celda.lesson)

    def context_menu(self, day: int, period: int) -> QMenu | None:
        """Menú contextual de una celda ocupada (`None` si no hay clase ahí)."""
        celda = self.primary(day, period)
        if celda is None:
            return None
        self.select_cell(day, period)
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        fijar = make_action(
            menu, "unfix" if celda.fixed else "fix", lambda: self.toggle_fixed(day, period)
        )
        set_texts(
            fijar,
            self.tr("Desfijar") if celda.fixed else self.tr("Fijar"),
            self.tr("Deja que la optimización la mueva")
            if celda.fixed
            else self.tr("La optimización no la moverá de aquí"),
        )
        desprogramar = make_action(menu, "unplace", lambda: self.unplace(day, period))
        set_texts(
            desprogramar,
            self.tr("Desprogramar (F7)"),
            self.tr("Saca la clase de esta hora y la aparca en la lista Sin colocar"),
        )
        abrir = make_action(menu, "lessons", lambda: self.open_lesson(day, period))
        set_texts(
            abrir,
            self.tr("Abrir lección {0}").format(celda.lesson),
            self.tr("Muestra la lección en la ventana Lecciones"),
        )
        menu.addAction(fijar)
        menu.addAction(desprogramar)
        menu.addSeparator()
        menu.addAction(abrir)
        return menu


def window_icon_for(kind: str) -> str:
    """Icono semántico del tipo de horario (para la ventana hija y la cinta)."""
    return KIND_ICONS.get(kind, "timetables")
