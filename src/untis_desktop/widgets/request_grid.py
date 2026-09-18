"""Rejilla de deseos de tiempo: días x períodos pintados de -3 (rojo) a +3 (verde).

Widget "tonto": muestra un `RequestGrid` de la Fachada y emite `painted` con las
celdas que el usuario pinta (clic o arrastre con el botón izquierdo = valor de la
paleta; botón derecho = borrar). La primera columna y la cabecera de fila son el
deseo de día completo. Los recreos se ven en gris y no se pueden pintar.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from scheduling_platform.application import RequestGrid

from ..theme import BREAK_COLOR, day_name, request_color, text_color_for

#: Una celda pintable: `(día, período)`; período `None` = día completo.
type RequestCell = tuple[int, int | None]


def request_text(value: int) -> str:
    """Texto de una celda: el valor con signo (vacío si no hay deseo)."""
    return f"{value:+d}" if value else ""


def request_meaning(value: int) -> str:
    """Qué significa un valor de deseo -3..+3, en palabras."""
    textos = {
        -3: QCoreApplication.translate("RequestGrid", "-3: imposible, nunca aquí"),
        -2: QCoreApplication.translate("RequestGrid", "-2: muy poco deseable"),
        -1: QCoreApplication.translate("RequestGrid", "-1: poco deseable"),
        0: QCoreApplication.translate("RequestGrid", "0: sin deseo (borra el valor)"),
        1: QCoreApplication.translate("RequestGrid", "+1: deseable"),
        2: QCoreApplication.translate("RequestGrid", "+2: bastante deseable"),
        3: QCoreApplication.translate("RequestGrid", "+3: muy deseable"),
    }
    return textos.get(max(-3, min(3, value)), "")


class RequestGridWidget(QTableWidget):
    """Días en filas; columna 0 = día completo; luego un período por columna."""

    painted = Signal(object, int)
    """`(list[RequestCell], valor)` al soltar el ratón."""

    def __init__(self) -> None:
        super().__init__(0, 0)
        self.grid: RequestGrid | None = None
        self.language = "es"
        self.paint_value = -3
        """Valor de la paleta que pinta el botón izquierdo."""
        self._drag: list[RequestCell] | None = None
        self._drag_value = 0
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(False)
        self.verticalHeader().setSectionsClickable(True)
        self.verticalHeader().sectionClicked.connect(self._on_day_header)
        self.horizontalHeader().setDefaultSectionSize(44)
        self.horizontalHeader().setMinimumSectionSize(36)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setDefaultSectionSize(30)

    # --- contenido ------------------------------------------------------------ #

    def set_grid(self, grid: RequestGrid | None, language: str = "es") -> None:
        self.grid = grid
        self.language = language
        if grid is None:
            self.setRowCount(0)
            self.setColumnCount(0)
            return
        self.setRowCount(len(grid.days))
        self.setColumnCount(len(grid.periods) + 1)
        self.setVerticalHeaderLabels([day_name(d, language) for d in grid.days])
        self.setHorizontalHeaderLabels([self.tr("Día"), *(str(p) for p in grid.periods)])
        cabecera = self.horizontalHeaderItem(0)
        if cabecera is not None:
            cabecera.setToolTip(self.tr("Deseo para el día entero (clic en el nombre del día)"))
        for fila, dia in enumerate(grid.days):
            self._set_cell(fila, 0, grid.day_values.get(dia, 0), is_break=False)
            for col, periodo in enumerate(grid.periods, start=1):
                recreo = periodo in grid.breaks
                self._set_cell(fila, col, 0 if recreo else grid.value(dia, periodo), recreo)

    def _set_cell(self, row: int, column: int, value: int, is_break: bool) -> None:
        item = QTableWidgetItem(request_text(value))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if is_break:
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setBackground(QColor(BREAK_COLOR))
            item.setToolTip(self.tr("Recreo: no hay clase"))
        else:
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            fondo = request_color(value)
            item.setBackground(fondo)
            item.setForeground(text_color_for(fondo))
            periodos = self.grid.periods if self.grid is not None else ()
            if column == 0:
                donde = self.tr("Todo el día")
            elif column - 1 < len(periodos):
                donde = self.tr("Período {0}").format(periodos[column - 1])
            else:
                donde = ""
            item.setToolTip(f"{donde}: {request_meaning(value)}")
        self.setItem(row, column, item)

    def cell_of(self, row: int, column: int) -> RequestCell | None:
        """Celda del modelo en `(fila, columna)`, o `None` si es un recreo."""
        grid = self.grid
        if grid is None or not 0 <= row < len(grid.days):
            return None
        dia = grid.days[row]
        if column == 0:
            return (dia, None)
        if not 1 <= column <= len(grid.periods):
            return None
        periodo = grid.periods[column - 1]
        return None if periodo in grid.breaks else (dia, periodo)

    def position_of(self, day: int, period: int | None) -> tuple[int, int]:
        """`(fila, columna)` de una celda del modelo."""
        grid = self.grid
        if grid is None:
            raise ValueError("Sin rejilla")
        columna = 0 if period is None else grid.periods.index(period) + 1
        return grid.days.index(day), columna

    def value_at(self, day: int, period: int | None) -> str:
        fila, col = self.position_of(day, period)
        item = self.item(fila, col)
        return item.text() if item is not None else ""

    def color_at(self, day: int, period: int | None) -> QColor:
        fila, col = self.position_of(day, period)
        item = self.item(fila, col)
        return item.background().color() if item is not None else QColor()

    # --- pintar con el ratón ---------------------------------------------------- #

    def _preview(self, cell: RequestCell) -> None:
        fila, col = self.position_of(*cell)
        self._set_cell(fila, col, self._drag_value, is_break=False)

    def _add(self, index: QModelIndex) -> None:
        if self._drag is None or not index.isValid():
            return
        celda = self.cell_of(index.row(), index.column())
        if celda is not None and celda not in self._drag:
            self._drag.append(celda)
            self._preview(celda)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        indice = self.indexAt(event.position().toPoint())
        if self.grid is None or not indice.isValid():
            super().mousePressEvent(event)
            return
        derecho = event.button() == Qt.MouseButton.RightButton
        self._drag_value = 0 if derecho else self.paint_value
        self._drag = []
        self._add(indice)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is None:
            super().mouseMoveEvent(event)
            return
        self._add(self.indexAt(event.position().toPoint()))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag is None:
            super().mouseReleaseEvent(event)
            return
        self._add(self.indexAt(event.position().toPoint()))
        celdas, self._drag = self._drag, None
        if celdas:
            self.painted.emit(celdas, self._drag_value)
        event.accept()

    def cell_center(self, day: int, period: int | None) -> QPoint:
        """Centro de una celda en coordenadas del *viewport* (pruebas, atajos)."""
        fila, col = self.position_of(day, period)
        return self.visualRect(self.model().index(fila, col)).center()

    def _on_day_header(self, row: int) -> None:
        celda = self.cell_of(row, 0)
        if celda is not None:
            self.painted.emit([celda], self.paint_value)
