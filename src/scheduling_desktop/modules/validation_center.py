"""Módulo 7 · Validation Center: todos los problemas del proyecto, navegables.

Consolida factibilidad estructural + consistencia del ``.bjs`` (vía la Fachada) y
los lista con severidad y ubicación. Doble-clic salta al módulo del elemento. La
UI no valida nada por su cuenta: solo pinta lo que el motor reporta.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import ValidationItem

from ..engine_bridge import EngineBridge
from . import PAGE_DATA, PAGE_SCHEDULE

# Palabras que sugieren que el problema vive en los datos (no en el horario).
_DATA_HINTS = ("docente", "teacher", "aula", "room", "grupo", "group", "recurso", "materia")


class ValidationCenterModule(QWidget):
    """Centro de validación: errores y avisos con navegación al elemento."""

    navigate = Signal(str)

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge

        self._summary = QLabel("Sin validar")
        self._summary.setStyleSheet("font-size: 15px; font-weight: 700;")
        revalidate = QPushButton("Validar de nuevo")
        revalidate.clicked.connect(self.refresh)
        top = QHBoxLayout()
        top.addWidget(self._summary, stretch=1)
        top.addWidget(revalidate)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Severidad", "Mensaje", "Dónde"])
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree.itemActivated.connect(self._on_item)
        self._tree.itemDoubleClicked.connect(self._on_item)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._tree, stretch=1)

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        report = self._bridge.validate()
        estado = "✔ FACTIBLE" if report.feasible else "✗ INFACTIBLE"
        self._summary.setText(
            f"{estado}  ·  {len(report.errors)} errores, {len(report.warnings)} avisos"
        )
        self._tree.clear()
        if not report.items:
            leaf = QTreeWidgetItem(["✔", "Sin problemas detectados", ""])
            self._tree.addTopLevelItem(leaf)
            return
        for item in report.items:
            icon = "✗" if item.severity == "error" else "⚠"
            node = QTreeWidgetItem([icon, item.message, item.where])
            node.setData(0, int(Qt.ItemDataRole.UserRole), self._page_for(item))
            self._tree.addTopLevelItem(node)
        self._tree.resizeColumnToContents(0)

    def _page_for(self, item: ValidationItem) -> str:
        haystack = f"{item.message} {item.where}".lower()
        if any(hint in haystack for hint in _DATA_HINTS):
            return PAGE_DATA
        return PAGE_SCHEDULE

    def _on_item(self, item: QTreeWidgetItem, _column: int) -> None:
        page = item.data(0, int(Qt.ItemDataRole.UserRole))
        if isinstance(page, str):
            self.navigate.emit(page)
