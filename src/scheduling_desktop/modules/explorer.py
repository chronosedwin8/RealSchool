"""Módulo 1 · Explorer: navegador jerárquico del proyecto (dock izquierdo).

Al estilo de Untis: un árbol con el proyecto y sus secciones (tablero, datos,
horario, optimización) con conteos en vivo. Doble-clic navega al módulo. Solo
lee conteos de la Fachada; no contiene lógica.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from ..engine_bridge import EngineBridge
from . import PAGE_DASHBOARD, PAGE_DATA, PAGE_OPTIMIZE, PAGE_SCHEDULE

_PAGE_ROLE = int(Qt.ItemDataRole.UserRole)


class ExplorerTree(QTreeWidget):
    """Árbol de navegación del proyecto."""

    navigate = Signal(str)

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.itemActivated.connect(self._on_item)
        self.itemClicked.connect(self._on_item)
        bridge.session_changed.connect(self.refresh)

    def refresh(self) -> None:
        self.clear()
        if not self._bridge.has_session:
            return
        stats = self._bridge.dashboard()
        root = QTreeWidgetItem([stats.project_name])
        self.addTopLevelItem(root)

        self._leaf(root, "Tablero", PAGE_DASHBOARD)
        datos = QTreeWidgetItem(["Datos"])
        root.addChild(datos)
        self._leaf(datos, f"Docentes ({stats.teachers})", PAGE_DATA)
        self._leaf(datos, f"Aulas ({stats.rooms})", PAGE_DATA)
        self._leaf(datos, f"Grupos ({stats.groups})", PAGE_DATA)
        self._leaf(datos, f"Materias ({stats.subjects})", PAGE_DATA)
        self._leaf(root, f"Horario ({stats.tasks} clases)", PAGE_SCHEDULE)
        self._leaf(root, "Optimización", PAGE_OPTIMIZE)
        self.expandAll()

    def _leaf(self, parent: QTreeWidgetItem, label: str, page: str) -> None:
        item = QTreeWidgetItem([label])
        item.setData(0, _PAGE_ROLE, page)
        parent.addChild(item)

    def _on_item(self, item: QTreeWidgetItem, _column: int) -> None:
        page = item.data(0, _PAGE_ROLE)
        if isinstance(page, str):
            self.navigate.emit(page)
