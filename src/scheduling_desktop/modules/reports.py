"""Módulo 8 · Reports: informes del horario, exportables.

Muestra los informes que calcula el motor (carga docente, uso de aulas, resumen
de calidad) y permite exportarlos a CSV. La UI no calcula métricas: solo pinta
las ``ReportTable`` de la Fachada y serializa filas a CSV (presentación).
"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import ReportTable

from ..engine_bridge import EngineBridge


class ReportsModule(QWidget):
    """Generador de informes con exportación a CSV."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._tables: dict[str, ReportTable] = {}

        self._picker = QComboBox()
        self._picker.currentIndexChanged.connect(self._show_current)
        self._export = QPushButton("Exportar CSV")
        self._export.clicked.connect(self._on_export)

        top = QHBoxLayout()
        top.addWidget(QLabel("Informe:"))
        top.addWidget(self._picker, stretch=1)
        top.addWidget(self._export)

        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._table, stretch=1)

        bridge.session_changed.connect(self.refresh)

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        current = self._picker.currentData()
        reports = self._bridge.reports()
        self._tables = {r.key: r for r in reports}
        self._picker.blockSignals(True)
        self._picker.clear()
        for report in reports:
            self._picker.addItem(report.title, report.key)
        index = self._picker.findData(current)
        self._picker.setCurrentIndex(index if index >= 0 else 0)
        self._picker.blockSignals(False)
        self._show_current()

    def _current(self) -> ReportTable | None:
        key = self._picker.currentData()
        return self._tables.get(key) if isinstance(key, str) else None

    def _show_current(self) -> None:
        report = self._current()
        self._export.setEnabled(report is not None and report.key != "empty")
        if report is None:
            self._table.clear()
            return
        self._table.setColumnCount(len(report.columns))
        self._table.setHorizontalHeaderLabels(list(report.columns))
        self._table.setRowCount(len(report.rows))
        for r, row in enumerate(report.rows):
            for c, value in enumerate(row):
                self._table.setItem(r, c, QTableWidgetItem(value))
        self._table.resizeColumnsToContents()
        header = self._table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)

    def _on_export(self) -> None:
        report = self._current()
        if report is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar informe", f"{report.key}.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with Path(path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(report.columns)
            writer.writerows(report.rows)
        self._bridge.status_message.emit(f"Informe exportado: {Path(path).name}")
