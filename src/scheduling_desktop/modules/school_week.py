"""Módulo · Semana lectiva: el marco horario por sección, como en Untis.

Cada **sección** (Kinder/Primaria/Bachillerato) tiene su propia estructura
horaria: número de días lectivos, períodos por día, corte Mañana/Tarde, horas de
reloj de cada período y **recreos**. Las lecciones se **asignan** a una semana
lectiva desde la Carga (columna *Semana lect.*), porque no todas comparten
estructura. El motor respeta los recreos y el tope de períodos de la semana de
cada clase. Todo se enruta a la Fachada.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
_ROWS = ("Inicio", "Fin", "Franja")
_START_ROW, _END_ROW, _BAND_ROW = 0, 1, 2
_MAX_PERIODS = 30


class _GenerateDialog(QDialog):
    """Pide la duración de cada hora y el descanso entre horas para autogenerar."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generar horas")
        self._duration = QSpinBox()
        self._duration.setRange(1, 240)
        self._duration.setValue(45)
        self._duration.setSuffix(" min")
        self._gap = QSpinBox()
        self._gap.setRange(0, 120)
        self._gap.setValue(0)
        self._gap.setSuffix(" min")
        form = QFormLayout()
        form.addRow("Duración de cada hora:", self._duration)
        form.addRow("Descanso entre horas:", self._gap)
        info = QLabel(
            "Se rellenan todas las horas desde el inicio de P0 (que debes haber\n"
            "ingresado antes). Los recreos se marcan aparte en la fila Franja."
        )
        info.setStyleSheet("color: #64748b;")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[int, int]:
        return self._duration.value(), self._gap.value()


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
        self._periods = QSpinBox()
        self._periods.setRange(1, _MAX_PERIODS)
        self._periods.setToolTip("Número de períodos (horas) por día de esta sección")
        self._periods.valueChanged.connect(lambda v: self._set_field("max_periods", v))
        self._afternoon = QSpinBox()
        self._afternoon.setToolTip("Primer período de la Tarde (los anteriores son Mañana)")
        self._afternoon.valueChanged.connect(lambda v: self._set_field("afternoon_from", v))
        self._gen_btn = QPushButton("Generar horas…")
        self._gen_btn.setToolTip("Rellena inicio/fin de todas las horas desde el inicio de P0")
        self._gen_btn.clicked.connect(self._on_generate)

        top = QHBoxLayout()
        top.addWidget(QLabel("Semana lectiva:"))
        top.addWidget(self._week)
        top.addWidget(new_btn)
        top.addWidget(rename_btn)
        top.addWidget(del_btn)
        top.addStretch(1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Días:"))
        controls.addWidget(self._days)
        controls.addSpacing(12)
        controls.addWidget(QLabel("Períodos/día:"))
        controls.addWidget(self._periods)
        controls.addSpacing(12)
        controls.addWidget(QLabel("Tarde desde P:"))
        controls.addWidget(self._afternoon)
        controls.addSpacing(12)
        controls.addWidget(self._gen_btn)
        controls.addStretch(1)

        self._hint = QLabel()
        self._hint.setStyleSheet("color: #64748b;")

        self._table = QTableWidget()
        self._table.setRowCount(len(_ROWS))
        self._table.setVerticalHeaderLabels(list(_ROWS))
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(controls)
        layout.addWidget(self._hint)
        layout.addWidget(self._table, stretch=1)

        bridge.session_refreshed.connect(self._defer_refresh)

    # --- refresco seguro ------------------------------------------------- #
    def _defer_refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._do_deferred_refresh)

    def _do_deferred_refresh(self) -> None:
        self._refresh_pending = False
        if not self._bridge.has_session:
            return
        # Si cambió la LISTA de semanas, reconstruye el combo; si solo cambió un
        # campo de la semana actual, repinta la rejilla (evita glitches del combo
        # y de los spinboxes al editar rápido).
        names = [w.name for w in self._bridge.school_weeks()]
        combo_names = [self._week.itemText(i) for i in range(self._week.count())]
        if names != combo_names:
            self.refresh()
        else:
            self._reload()

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
        _, periods = self._bridge.grid_size()
        try:
            index = self._bridge.add_school_week(name.strip(), max_periods=periods)
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
    def _periods_count(self, week: object) -> int:
        max_periods = getattr(week, "max_periods", 0)
        if max_periods > 0:
            return int(max_periods)
        return self._bridge.grid_size()[1]

    def _reload(self) -> None:
        index = self._week.currentIndex()
        weeks = self._bridge.school_weeks() if self._bridge.has_session else ()
        self._loading = True
        if not (0 <= index < len(weeks)):
            self._table.setColumnCount(0)
            for control in (self._days, self._periods, self._afternoon, self._gen_btn):
                control.setEnabled(False)
            self._hint.setText(
                "Crea una semana lectiva con 'Nueva...' para definir el marco horario "
                "de una sección (Kinder, Primaria, Bachillerato...)."
            )
            self._hint.setStyleSheet("color: #b45309; font-weight: 600;")
            self._loading = False
            return
        self._hint.setText(
            "Escribe las horas en Inicio/Fin (HH:MM) o pulsa 'Generar horas...' · "
            "clic en la fila Franja marca/quita un Recreo."
        )
        self._hint.setStyleSheet("color: #64748b;")
        week = weeks[index]
        periods = self._periods_count(week)
        for control in (self._days, self._periods, self._afternoon, self._gen_btn):
            control.setEnabled(True)
        self._set_spin(self._days, 1, 7, week.days)
        self._set_spin(self._periods, 1, _MAX_PERIODS, periods)
        self._set_spin(
            self._afternoon,
            0,
            periods,
            week.afternoon_from if week.afternoon_from >= 0 else periods,
        )

        breaks = set(week.breaks)
        self._table.setColumnCount(periods)
        self._table.setHorizontalHeaderLabels([f"P{p}" for p in range(periods)])
        for p in range(periods):
            clock = week.periods[p] if p < len(week.periods) else None
            self._set_cell(_START_ROW, p, clock.start if clock else "")
            self._set_cell(_END_ROW, p, clock.end if clock else "")
            if p in breaks:
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

    @staticmethod
    def _set_spin(spin: QSpinBox, low: int, high: int, value: int) -> None:
        spin.blockSignals(True)
        spin.setRange(low, high)
        spin.setValue(max(low, min(high, value)))
        spin.blockSignals(False)

    def _set_cell(self, row: int, col: int, text: str) -> None:
        self._table.setItem(row, col, QTableWidgetItem(text))

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

    def _on_generate(self) -> None:
        index = self._week.currentIndex()
        if index < 0:
            return
        dialog = _GenerateDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        duration, gap = dialog.values()
        try:
            self._bridge.generate_school_week_times(index, duration, gap)
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudieron generar las horas", str(exc))

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
            self._reload()  # revierte la celda al valor válido anterior
