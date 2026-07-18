"""Módulo · Desiderata (Peti/Desid): bloqueo de horas de grupos y docentes.

Como en Untis: se elige un recurso y se marcan en una rejilla las horas en que
**no** puede haber clase (clic en la celda; clic en la cabecera bloquea toda la
fila/columna). Los **grupos y aulas** se bloquean por **período** (P3 recreo, P9
almuerzo...); los **docentes** por **hora de reloj** (pueden dar clases en varias
semanas lectivas con horas distintas). La desiderata de un recurso se puede
**copiar** a otros del mismo tipo (6A -> 6B, 6C, 6D). Todo pasa por la Fachada.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..engine_bridge import EngineBridge
from ..theme import day_name

_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_BLOCKED = QColor("#fca5a5")  # rojo claro (bloqueada = sin clase)
_FREE = QColor("#ffffff")
_BLOCKED_INK = QColor("#7f1d1d")


class _CopyDialog(QDialog):
    """Elige a qué recursos (del mismo tipo) copiar la desiderata."""

    def __init__(self, parent: QWidget, *, title: str, options: list[tuple[int, str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for rid, name in options:
            self._list.addItem(name)
            self._list.item(self._list.count() - 1).setData(_ID_ROLE, rid)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Copiar los bloqueos a:"))
        layout.addWidget(self._list)
        layout.addWidget(buttons)

    def selected(self) -> list[int]:
        return [item.data(_ID_ROLE) for item in self._list.selectedItems()]


class DesiderataModule(QWidget):
    """Editor de bloqueos (desiderata) por grupo/aula (período) o docente (reloj)."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._loading = False
        self._refresh_pending = False

        self._resource = QComboBox()
        self._resource.setMinimumWidth(240)
        self._resource.currentIndexChanged.connect(self._reload)
        self._copy_btn = QPushButton("Copiar a…")
        self._copy_btn.setToolTip("Copia estos bloqueos a otros recursos del mismo tipo")
        self._copy_btn.clicked.connect(self._on_copy)
        self._clear_btn = QPushButton("Limpiar")
        self._clear_btn.clicked.connect(self._on_clear)

        top = QHBoxLayout()
        top.addWidget(QLabel("Recurso:"))
        top.addWidget(self._resource)
        top.addWidget(self._copy_btn)
        top.addWidget(self._clear_btn)
        top.addStretch(1)

        self._hint = QLabel()
        self._hint.setStyleSheet("color: #64748b;")

        self._table = QTableWidget()
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.horizontalHeader().sectionClicked.connect(self._on_col_clicked)
        self._table.verticalHeader().sectionClicked.connect(self._on_row_clicked)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
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
        self.refresh()

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        previous = self._resource.currentData()
        self._resource.blockSignals(True)
        self._resource.clear()
        for option in self._bridge.focus_options():
            label = {"teacher": "Docente", "group": "Grupo", "room": "Aula"}.get(
                option.kind, option.kind
            )
            self._resource.addItem(f"{label}: {option.name}", option.resource_id)
        index = self._resource.findData(previous)
        self._resource.setCurrentIndex(index if index >= 0 else 0)
        self._resource.blockSignals(False)
        self._reload()

    # --- rejilla --------------------------------------------------------- #
    def _current(self) -> int:
        rid = self._resource.currentData()
        return rid if isinstance(rid, int) else -1

    def _reload(self) -> None:
        rid = self._current()
        if not self._bridge.has_session or rid < 0:
            self._table.clear()
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            return
        kind = self._bridge.block_kind(rid)
        days, periods = self._bridge.grid_size()
        self._loading = True
        self._table.clear()
        self._table.setRowCount(days)
        self._table.setVerticalHeaderLabels([day_name(d, days) for d in range(days)])
        if kind == "clock":
            self._reload_clock(rid, days)
            self._hint.setText(
                "Docente: clic en una hora de reloj para bloquearla (no dará clase ahí). "
                "Bloquea por reloj porque puede estar en varias semanas lectivas."
            )
        else:
            self._reload_period(rid, days, periods)
            self._hint.setText(
                "Grupo/aula: clic en un período para bloquearlo (P3 recreo, P9 almuerzo...). "
                "Clic en la cabecera bloquea toda la fila o columna."
            )
        self._table.resizeColumnsToContents()
        self._loading = False

    def _reload_period(self, rid: int, days: int, periods: int) -> None:
        blocked = self._bridge.blocked_hours(rid)
        self._table.setColumnCount(periods)
        self._table.setHorizontalHeaderLabels([f"P{p + 1}" for p in range(periods)])
        for d in range(days):
            for p in range(periods):
                self._set_cell(d, p, (d, p) in blocked)

    def _reload_clock(self, rid: int, days: int) -> None:
        low, high = self._bridge.clock_range()
        hours = list(range(low, high))
        blocked = self._bridge.teacher_time_blocks(rid)
        self._table.setColumnCount(len(hours))
        self._table.setHorizontalHeaderLabels([f"{h:02d}:00" for h in hours])
        for d in range(days):
            for col, h in enumerate(hours):
                self._set_cell(d, col, (d, h) in blocked)

    def _set_cell(self, row: int, col: int, blocked: bool) -> None:
        item = QTableWidgetItem("X" if blocked else "")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setBackground(_BLOCKED if blocked else _FREE)
        if blocked:
            item.setForeground(_BLOCKED_INK)
        self._table.setItem(row, col, item)

    # --- interacción ----------------------------------------------------- #
    def _col_value(self, col: int) -> int:
        """Valor lógico de la columna: período (period) u hora de reloj (clock)."""
        if self._bridge.block_kind(self._current()) == "clock":
            low, _ = self._bridge.clock_range()
            return low + col
        return col

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if self._loading:
            return
        rid = self._current()
        if rid < 0:
            return
        value = self._col_value(col)
        if self._bridge.block_kind(rid) == "clock":
            self._bridge.toggle_time_block(rid, row, value)
        else:
            self._bridge.toggle_block(rid, row, value)

    def _on_col_clicked(self, col: int) -> None:
        self._toggle_bulk(cols=[col], rows=range(self._table.rowCount()))

    def _on_row_clicked(self, row: int) -> None:
        self._toggle_bulk(cols=range(self._table.columnCount()), rows=[row])

    def _toggle_bulk(self, *, cols: range | list[int], rows: range | list[int]) -> None:
        """Bloquea toda una fila/columna (o la libera si ya estaba toda bloqueada)."""
        if self._loading:
            return
        rid = self._current()
        if rid < 0:
            return
        clock = self._bridge.block_kind(rid) == "clock"
        current = set(
            self._bridge.teacher_time_blocks(rid) if clock else self._bridge.blocked_hours(rid)
        )
        targets = {(r, self._col_value(c)) for r in rows for c in cols}
        # Si ya están todas bloqueadas, se liberan; si no, se bloquean todas.
        current = current - targets if targets <= current else current | targets
        if clock:
            self._bridge.set_time_blocks(rid, current)
        else:
            self._bridge.set_blocked(rid, current)

    def _on_clear(self) -> None:
        rid = self._current()
        if rid < 0:
            return
        if self._bridge.block_kind(rid) == "clock":
            self._bridge.set_time_blocks(rid, set())
        else:
            self._bridge.set_blocked(rid, set())

    def _on_copy(self) -> None:
        rid = self._current()
        if rid < 0:
            return
        kind = self._bridge.block_kind(rid)
        same = [
            (o.resource_id, o.name)
            for o in self._bridge.focus_options()
            if o.resource_id != rid and self._bridge.block_kind(o.resource_id) == kind
        ]
        if not same:
            QMessageBox.information(self, "Copiar", "No hay otros recursos del mismo tipo.")
            return
        dialog = _CopyDialog(self, title="Copiar desiderata", options=same)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        targets = dialog.selected()
        if targets:
            self._bridge.copy_blocks(rid, targets)
