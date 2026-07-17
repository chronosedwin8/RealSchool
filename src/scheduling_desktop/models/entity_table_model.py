"""``EntityTableModel``: adapta una ``EntityTable`` de la Fachada a un QTableView.

Es un modelo de solo presentación: los datos vienen ya calculados del motor. Las
columnas marcadas como editables enrutan el cambio a un callback (que llama a la
Fachada). Con ``on_create`` el modelo añade una **fila vacía al final** (como
Untis/Excel): escribir la abreviatura en ella crea el registro. El modelo no
conoce ninguna regla de negocio.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor

from scheduling_platform.application import EntityTable

_Index = QModelIndex | QPersistentModelIndex
_NO_PARENT = QModelIndex()

#: (clave de fila, índice de columna, valor nuevo) -> éxito.
EditCallback = Callable[[str, int, str], bool]
#: (abreviatura escrita en la fila vacía) -> éxito.
CreateCallback = Callable[[str], bool]


class EntityTableModel(QAbstractTableModel):
    """Tabla tipo Excel de una clase de entidad (docentes, aulas, grupos, materias)."""

    def __init__(
        self,
        table: EntityTable,
        *,
        editable: frozenset[int] = frozenset(),
        on_edit: EditCallback | None = None,
        on_create: CreateCallback | None = None,
    ) -> None:
        super().__init__()
        self._table = table
        self._editable = editable
        self._on_edit = on_edit
        self._on_create = on_create

    def _is_blank(self, row: int) -> bool:
        """La fila vacía del final, para crear un registro escribiendo en ella."""
        return self._on_create is not None and row == len(self._table.rows)

    def rowCount(self, parent: _Index = _NO_PARENT) -> int:
        if parent.isValid():
            return 0
        return len(self._table.rows) + (1 if self._on_create is not None else 0)

    def columnCount(self, parent: _Index = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self._table.columns)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._table.columns[section]
        return "*" if self._is_blank(section) else section + 1

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        if self._is_blank(index.row()):
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
                return ""
            return None
        value = self._table.rows[index.row()].cells[index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return value
        if (
            role == Qt.ItemDataRole.BackgroundRole
            and self._is_color_column(index.column())
            and value.startswith("#")
        ):
            return QColor(value)
        return None

    def _is_color_column(self, column: int) -> bool:
        fields = self._table.fields
        return bool(fields) and column < len(fields) and fields[column] == "color"

    def flags(self, index: _Index) -> Qt.ItemFlag:
        base = super().flags(index)
        if self._is_blank(index.row()):
            # En la fila vacía solo se escribe la abreviatura (columna 0).
            return base | Qt.ItemFlag.ItemIsEditable if index.column() == 0 else base
        if self._on_edit is not None and index.column() in self._editable:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: _Index, value: object, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole:
            return False
        text = str(value).strip()
        if self._is_blank(index.row()):
            if self._on_create is None or index.column() != 0 or not text:
                return False
            return self._on_create(text)
        if self._on_edit is None or index.column() not in self._editable:
            return False
        row = self._table.rows[index.row()]
        return self._on_edit(row.key, index.column(), str(value))
