"""Ventana Rejillas de tiempo: una pestaña por rejilla (sección 8).

Cada pestaña es una tabla período x (Inicio, Fin, Recreo, Tarde) editable en
celda y la lista de clases que usan la rejilla. Los recreos se pintan en gris;
una hora rechazada por la Fachada queda en rojo con el motivo.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import EditResult, GridView

from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import BREAK_COLOR, ERROR_COLOR

COL_START, COL_END, COL_BREAK, COL_AFTERNOON = range(4)


class GridPage(QWidget):
    """Una rejilla: tabla de períodos y clases que la usan."""

    def __init__(self, bridge: FacadeBridge, grid: GridView) -> None:
        super().__init__()
        self.bridge = bridge
        self.grid = grid
        self._errors: dict[tuple[int, int], str] = {}
        self._loading = False

        self.table = QTableWidget(0, 4)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._on_item_changed)
        self.classes_label = QLabel()
        self.classes = QListWidget()
        self.classes.setMaximumWidth(180)

        lateral = QVBoxLayout()
        lateral.addWidget(self.classes_label)
        lateral.addWidget(self.classes, 1)
        raiz = QHBoxLayout(self)
        raiz.addWidget(self.table, 1)
        raiz.addLayout(lateral)
        self.retranslate()
        self.set_grid(grid)

    def set_grid(self, grid: GridView) -> None:
        self.grid = grid
        self._loading = True
        try:
            self.table.setRowCount(len(grid.periods))
            self.table.setVerticalHeaderLabels([str(p.number) for p in grid.periods])
            for fila, p in enumerate(grid.periods):
                for col, texto in ((COL_START, p.start), (COL_END, p.end)):
                    self.table.setItem(fila, col, QTableWidgetItem(texto))
                for col, marcado in ((COL_BREAK, p.is_break), (COL_AFTERNOON, p.afternoon)):
                    item = QTableWidgetItem()
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked
                    )
                    self.table.setItem(fila, col, item)
                self._paint_row(fila)
            self.classes.clear()
            self.classes.addItems(list(grid.classes))
        finally:
            self._loading = False

    def _paint_row(self, row: int) -> None:
        periodo = self.grid.periods[row]
        for col in range(4):
            item = self.table.item(row, col)
            if item is None:
                continue
            error = self._errors.get((periodo.number, col), "")
            if error:
                item.setBackground(QColor(ERROR_COLOR))
            elif periodo.is_break:
                item.setBackground(QColor(BREAK_COLOR))
            else:
                item.setBackground(QColor("#ffffff"))
            item.setToolTip(error)

    def row_of(self, number: int) -> int:
        return next((i for i, p in enumerate(self.grid.periods) if p.number == number), -1)

    def error_at(self, number: int, column: int) -> str:
        return self._errors.get((number, column), "")

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        fila, col = item.row(), item.column()
        if not 0 <= fila < len(self.grid.periods):
            return
        numero = self.grid.periods[fila].number
        marcado = item.checkState() == Qt.CheckState.Checked
        if col == COL_START:
            self.edit_period(numero, col, start=item.text().strip())
        elif col == COL_END:
            self.edit_period(numero, col, end=item.text().strip())
        elif col == COL_BREAK:
            self.edit_period(numero, col, is_break=marcado)
        elif col == COL_AFTERNOON:
            self.edit_period(numero, col, afternoon=marcado)

    def edit_period(
        self,
        number: int,
        column: int,
        *,
        start: str | None = None,
        end: str | None = None,
        is_break: bool | None = None,
        afternoon: bool | None = None,
    ) -> EditResult:
        """Edita un período; si la Fachada lo rechaza, la celda queda en rojo."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        svc, grid_id = self.bridge.service, self.grid.id
        if start == "" or end == "":
            resultado = EditResult.failure(self.tr("Indica una hora HH:MM"))
        else:
            resultado = self.bridge.edit(
                lambda: svc.set_period(
                    self.bridge.session,
                    grid_id,
                    number,
                    start=start,
                    end=end,
                    is_break=is_break,
                    afternoon=afternoon,
                )
            )
        if resultado.ok:
            self._errors.pop((number, column), None)
        else:
            self._errors[(number, column)] = resultado.message
            self.bridge.status.emit(resultado.message)
        fila = self.row_of(number)
        if fila >= 0:
            self._loading = True
            try:
                self._paint_row(fila)
            finally:
                self._loading = False
        return resultado

    def retranslate(self) -> None:
        self.table.setHorizontalHeaderLabels(
            [self.tr("Inicio"), self.tr("Fin"), self.tr("Recreo"), self.tr("Tarde")]
        )
        self.classes_label.setText(self.tr("Clases con esta rejilla"))


class TimeGridsWindow(QWidget):
    """Rejillas de tiempo del proyecto, una pestaña por rejilla."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.tabs = QTabWidget()
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)
        raiz.addWidget(self.tabs, 1)
        raiz.addWidget(self.empty)
        self.pages: dict[str, GridPage] = {}
        bridge.refreshed.connect(self.refresh)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()
        self.refresh()

    def refresh(self) -> None:
        grids = self.bridge.service.grids(self.bridge.session) if self.bridge.has_session else ()
        if tuple(self.pages) == tuple(g.id for g in grids):
            for g in grids:
                self.pages[g.id].set_grid(g)
        else:
            actual = self.tabs.currentIndex()
            self.tabs.clear()
            for page in self.pages.values():
                page.deleteLater()
            self.pages = {}
            for g in grids:
                page = GridPage(self.bridge, g)
                self.pages[g.id] = page
                self.tabs.addTab(page, g.name)
            if 0 <= actual < self.tabs.count():
                self.tabs.setCurrentIndex(actual)
        self.empty.setVisible(not grids)

    def page(self, grid_id: str) -> GridPage:
        return self.pages[grid_id]

    def _retranslate(self) -> None:
        self.empty.setText(self.tr("El proyecto no tiene rejillas de tiempo"))
        for page in self.pages.values():
            page.retranslate()


register(
    WindowSpec(
        key="time_grids",
        title="Rejillas de tiempo",
        title_de="Zeitraster",
        tab=RibbonTab.MASTER_DATA,
        factory=TimeGridsWindow,
        order=7,
    )
)
