"""``EntityTableModel``: adapta una ``EntityTable`` de la Fachada a un QTableView.

Es un modelo de solo presentación: los datos vienen ya calculados del motor. Las
columnas marcadas como editables enrutan el cambio a un callback (que llama a la
Fachada); el modelo no conoce ninguna regla de negocio.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from scheduling_platform.application import EntityTable

_Index = QModelIndex | QPersistentModelIndex
_NO_PARENT = QModelIndex()

#: (clave de fila, índice de columna, valor nuevo) -> éxito.
EditCallback = Callable[[str, int, str], bool]


class EntityTableModel(QAbstractTableModel):
    """Tabla tipo Excel de una clase de entidad (docentes, aulas, grupos, materias)."""

    def __init__(
        self,
        table: EntityTable,
        *,
        editable: frozenset[int] = frozenset(),
        on_edit: EditCallback | None = None,
    ) -> None:
        super().__init__()
        self._table = table
        self._editable = editable
        self._on_edit = on_edit

    def rowCount(self, parent: _Index = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self._table.rows)

    def columnCount(self, parent: _Index = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self._table.columns)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._table.columns[section]
        return section + 1

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._table.rows[index.row()].cells[index.column()]
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        base = super().flags(index)
        if self._on_edit is not None and index.column() in self._editable:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: _Index, value: object, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or self._on_edit is None:
            return False
        if index.column() not in self._editable:
            return False
        row = self._table.rows[index.row()]
        return self._on_edit(row.key, index.column(), str(value))
