"""Módulo 3 · Data Manager: los datos del proyecto como DataGrids tipo Excel.

Pestañas Docentes/Aulas/Grupos/Materias sobre ``QTableView``. v1: ver + edición
básica (renombrar; cupos de aula) enrutada a la Fachada. La UI no valida nada:
si el motor rechaza el cambio, la edición no se aplica.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTableView, QTabWidget, QVBoxLayout, QWidget

from scheduling_platform.application import EntityTable

from ..engine_bridge import EngineBridge
from ..models import EntityTableModel

_NAME_COL = 1


class DataManagerModule(QWidget):
    """Editor tabular de las entidades del proyecto."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._tabs = QTabWidget()
        self._views: dict[str, QTableView] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        bridge.session_changed.connect(self.refresh)

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        current = self._tabs.currentIndex()
        tables = self._bridge.tables()
        self._tabs.clear()
        self._views.clear()
        for table in tables.as_tuple():
            view = QTableView()
            view.setModel(self._model_for(table))
            view.resizeColumnsToContents()
            view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
            self._tabs.addTab(view, f"{table.title} ({len(table.rows)})")
            self._views[table.kind] = view
        if 0 <= current < self._tabs.count():
            self._tabs.setCurrentIndex(current)

    def _model_for(self, table: EntityTable) -> EntityTableModel:
        if table.kind == "teacher":
            return EntityTableModel(
                table, editable=frozenset({_NAME_COL}), on_edit=self._edit_resource
            )
        if table.kind == "group":
            return EntityTableModel(
                table, editable=frozenset({_NAME_COL}), on_edit=self._edit_resource
            )
        if table.kind == "room":
            return EntityTableModel(
                table, editable=frozenset({_NAME_COL, 2}), on_edit=self._edit_room
            )
        return EntityTableModel(table)  # materias: solo lectura

    # --- edición (enruta a la Fachada) ---------------------------------- #
    def _edit_resource(self, key: str, column: int, value: str) -> bool:
        value = value.strip()
        if column == _NAME_COL and value:
            return self._bridge.rename_resource(int(key), value)
        return False

    def _edit_room(self, key: str, column: int, value: str) -> bool:
        if column == _NAME_COL:
            return self._edit_resource(key, column, value)
        if column == 2:  # cupos
            try:
                seats = int(value)
            except ValueError:
                return False
            if seats < 1:
                return False
            return self._bridge.set_room_seats(int(key), seats)
        return False
