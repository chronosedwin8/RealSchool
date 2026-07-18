"""Módulo · Semana lectiva: el marco horario por sección, como en Untis.

Cada **sección** (Kinder/Primaria/Bachillerato) tiene su propia estructura
horaria: número de días lectivos, corte Mañana/Tarde, horas de reloj de cada
período y **recreos**. Las lecciones se **asignan** a una semana lectiva desde la
Carga (columna *Semana lect.*), porque no todas comparten estructura. El motor
respeta los recreos de la semana de cada clase. Todo se enruta a la Fachada.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import ConfigError

from ..engine_bridge import EngineBridge

_MORNING = QColor("#fed7aa")  # naranja claro (Mañana)
_AFTERNOON = QColor("#bae6fd")  # azul claro (Tarde)
_BREAK = QColor("#fde68a")  # amarillo (Recreo)
_DISABLED = QColor("#e2e8f0")  # gris (fuera del tope de períodos)
_ROWS = ("Inicio", "Fin", "Franja")
_START_ROW, _END_ROW, _BAND_ROW = 0, 1, 2


class SchoolWeekModule(QWidget):
    """Editor de las semanas lectivas (marcos horarios por sección)."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._loading = False
        self._refresh_pending = False

        self._week = QComboBox()
        self._week.setMinimumWidth(180)
        self._week.currentIndexChanged.connect(self._on_week_changed)
        new_btn = QPushButton("Nueva…")
        new_btn.clicked.connect(self._on_new)
        rename_btn = QPushButton("Renombrar…")
        rename_btn.clicked.connect(self._on_rename)
        del_btn = QPushButton("Eliminar")
        del_btn.clicked.connect(self._on_delete)

        self._days = QSpinBox()
        self._days.setRange(1, 7)
        self._days.setToolTip("Número de días lectivos semanales")
        self._days.valueChanged.connect(lambda v: self._set_field("days", v))
        self._afternoon = QSpinBox()
        self._afternoon.setToolTip("Primer período de la Tarde (los anteriores son Mañana)")
        self._afternoon.valueChanged.connect(lambda v: self._set_field("afternoon_from", v))

        top = QHBoxLayout()
        top.addWidget(QLabel("Semana lectiva:"))
        top.addWidget(self._week)
        top.addWidget(new_btn)
        top.addWidget(rename_btn)
        top.addWidget(del_btn)
        top.addSpacing(16)
        top.addWidget(QLabel("Días:"))
        top.addWidget(self._days)
        top.addWidget(QLabel("Tarde desde P:"))
        top.addWidget(self._afternoon)
        top.addStretch(1)

        self._hint = QLabel(
            "Escribe las horas de reloj en Inicio/Fin · clic en la fila Franja "
            "marca/quita un Recreo."
        )
        self._hint.setStyleSheet("color: #64748b;")

        self._table = QTableWidget()
        self._table.setRowCount(len(_ROWS))
        self._table.setVerticalHeaderLabels(list(_ROWS))
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._hint)
        layout.addWidget(self._table, stretch=1)

        bridge.session_changed.connect(self._defer_refresh)

    # --- refresco seguro ------------------------------------------------- #
    def _defer_refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._do_deferred_refresh)

    def _do_deferred_refresh(self) -> None:
        self._refresh_pending = False
        self.refresh()

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        weeks = self._bridge.school_weeks()
        previous = self._week.currentIndex()
        self._week.blockSignals(True)
        self._week.clear()
        for week in weeks:
            self._week.addItem(week.name)
        if weeks:
            self._week.setCurrentIndex(min(max(previous, 0), len(weeks) - 1))
        self._week.blockSignals(False)
        self._reload()

    # --- CRUD de semanas ------------------------------------------------- #
    def _on_new(self) -> None:
        if not self._bridge.has_session:
            return
        name, ok = QInputDialog.getText(self, "Nueva semana lectiva", "Nombre de la sección:")
        if not ok or not name.strip():
            return
        try:
            index = self._bridge.add_school_week(name.strip())
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo crear", str(exc))
            return
        self.refresh()
        self._week.setCurrentIndex(index)

    def _on_rename(self) -> None:
        index = self._week.currentIndex()
        if index < 0:
            return
        name, ok = QInputDialog.getText(
            self, "Renombrar semana lectiva", "Nuevo nombre:", text=self._week.currentText()
        )
        if not ok or not name.strip():
            return
        try:
            self._bridge.rename_school_week(index, name.strip())
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo renombrar", str(exc))

    def _on_delete(self) -> None:
        index = self._week.currentIndex()
        if index < 0:
            return
        name = self._week.currentText()
        if (
            QMessageBox.question(self, "Eliminar semana lectiva", f"¿Eliminar '{name}'?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._bridge.remove_school_week(index)
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo eliminar", str(exc))

    def _on_week_changed(self) -> None:
        self._reload()

    # --- rejilla del marco horario --------------------------------------- #
    def _reload(self) -> None:
        index = self._week.currentIndex()
        weeks = self._bridge.school_weeks() if self._bridge.has_session else ()
        self._loading = True
        if not (0 <= index < len(weeks)):
            self._table.setColumnCount(0)
            self._days.setEnabled(False)
            self._afternoon.setEnabled(False)
            self._hint.setText(
                "Crea una semana lectiva con 'Nueva...' para definir el marco horario "
                "de una sección (Kinder, Primaria, Bachillerato...)."
            )
            self._hint.setStyleSheet("color: #b45309; font-weight: 600;")
            self._loading = False
            return
        self._hint.setText(
            "Escribe las horas de reloj en Inicio/Fin · clic en la fila Franja "
            "marca/quita un Recreo."
        )
        self._hint.setStyleSheet("color: #64748b;")
        week = weeks[index]
        _, periods = self._bridge.grid_size()
        self._days.setEnabled(True)
        self._afternoon.setEnabled(True)
        self._days.setValue(week.days)
        self._afternoon.setRange(0, periods)
        self._afternoon.setValue(week.afternoon_from if week.afternoon_from >= 0 else periods)

        breaks = set(week.breaks)
        self._table.setColumnCount(periods)
        self._table.setHorizontalHeaderLabels([f"P{p}" for p in range(periods)])
        for p in range(periods):
            clock = week.periods[p] if p < len(week.periods) else None
            beyond = 0 < week.max_periods <= p
            self._set_cell(_START_ROW, p, clock.start if clock else "", editable=not beyond)
            self._set_cell(_END_ROW, p, clock.end if clock else "", editable=not beyond)
            if beyond:
                band, color = "—", _DISABLED
            elif p in breaks:
                band, color = "Recreo", _BREAK
            elif week.afternoon_from >= 0 and p >= week.afternoon_from:
                band, color = "Tarde", _AFTERNOON
            else:
                band, color = "Mañana", _MORNING
            band_item = QTableWidgetItem(band)
            band_item.setFlags(band_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            band_item.setBackground(color)
            self._table.setItem(_BAND_ROW, p, band_item)
        self._table.resizeColumnsToContents()
        self._loading = False

    def _set_cell(self, row: int, col: int, text: str, *, editable: bool) -> None:
        item = QTableWidgetItem(text)
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setBackground(_DISABLED)
        self._table.setItem(row, col, item)

    # --- edición --------------------------------------------------------- #
    def _set_field(self, field: str, value: int) -> None:
        if self._loading:
            return
        index = self._week.currentIndex()
        if index < 0:
            return
        try:
            self._bridge.set_school_week_field(index, field, value)
        except ConfigError as exc:
            QMessageBox.warning(self, "Valor no válido", str(exc))
        self._reload()

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if self._loading or row != _BAND_ROW:
            return
        index = self._week.currentIndex()
        if index < 0:
            return
        try:
            self._bridge.toggle_school_week_break(index, column)
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo cambiar el recreo", str(exc))
        self._reload()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.row() not in (_START_ROW, _END_ROW):
            return
        index = self._week.currentIndex()
        if index < 0:
            return
        period = item.column()
        start_item = self._table.item(_START_ROW, period)
        end_item = self._table.item(_END_ROW, period)
        start = start_item.text().strip() if start_item is not None else ""
        end = end_item.text().strip() if end_item is not None else ""
        try:
            self._bridge.set_school_week_period(index, period, start, end)
        except ConfigError as exc:
            QMessageBox.warning(self, "Hora no válida", str(exc))
