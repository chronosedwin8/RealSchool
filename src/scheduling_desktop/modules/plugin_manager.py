"""Módulo 12 · Plugin Manager: inventario de extensiones del motor.

Muestra qué restricciones, solvers, importadores y exportadores hay disponibles y
su estado. Las restricciones se activan/pesan en el Constraint Manager; aquí es
una vista de inventario (qué trae la plataforma).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..engine_bridge import EngineBridge


class PluginManagerModule(QWidget):
    """Inventario de extensiones disponibles en la plataforma."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge

        title = QLabel("Extensiones de la plataforma")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Extensión", "Estado"])
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self._tree, stretch=1)

        bridge.session_opened.connect(self.refresh)

    def refresh(self) -> None:
        self._tree.clear()
        if not self._bridge.has_session:
            return

        restr = QTreeWidgetItem(["Restricciones (catálogo)"])
        self._tree.addTopLevelItem(restr)
        for row in self._bridge.constraints_catalog():
            estado = "activa" if row.enabled else "disponible"
            leaf = QTreeWidgetItem([f"{row.catalog_id} · {row.name}", estado])
            restr.addChild(leaf)

        solvers = QTreeWidgetItem(["Solvers"])
        self._tree.addTopLevelItem(solvers)
        for name in self._bridge.available_solvers():
            solvers.addChild(QTreeWidgetItem([name, "disponible"]))

        io = QTreeWidgetItem(["Importadores / Exportadores"])
        self._tree.addTopLevelItem(io)
        io.addChild(QTreeWidgetItem(["Importar Untis (XML)", "disponible"]))
        io.addChild(QTreeWidgetItem(["Exportar JSON", "disponible"]))
        io.addChild(QTreeWidgetItem(["Exportar informes CSV", "disponible"]))

        self._tree.expandAll()
        self._tree.resizeColumnToContents(1)
