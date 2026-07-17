"""Módulo 3 · Data Manager: los datos del proyecto como DataGrids tipo Excel.

Pestañas Docentes/Aulas/Grupos/Materias sobre ``QTableView``: ver, **edición**
(renombrar, cupos, tamaño), **altas/bajas** (CRUD) y **carga horaria** (crear
clases por grupo/docente). Todo se enruta a la Fachada; la UI no valida reglas.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import ConfigError, EntityTable, EntityTables

from ..engine_bridge import EngineBridge
from ..models import EntityTableModel

_NAME_COL = 1
_KINDS = ("teacher", "room", "group", "subject")
_ID_ROLE = int(Qt.ItemDataRole.UserRole)


class _LoadDialog(QDialog):
    """Diálogo de carga: acopla varios docentes, grupos y (opcional) aulas."""

    def __init__(self, tables: EntityTables, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Añadir carga (una asignación)")
        self._subject = QLineEdit()
        self._sessions = QSpinBox()
        self._sessions.setRange(1, 40)
        self._teachers = self._multi_list(tables.teachers)
        self._groups = self._multi_list(tables.groups)
        self._rooms = self._multi_list(tables.rooms)

        form = QFormLayout()
        form.addRow("Materia:", self._subject)
        form.addRow("Sesiones/semana:", self._sessions)
        form.addRow(QLabel("Docentes (uno o varios):"), self._teachers)
        form.addRow(QLabel("Grupos (uno o varios):"), self._groups)
        form.addRow(QLabel("Aulas (opcional; vacío = el solver elige):"), self._rooms)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _multi_list(table: EntityTable) -> QListWidget:
        widget = QListWidget()
        widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        widget.setMaximumHeight(120)
        for row in table.rows:
            widget.addItem(row.cells[1])
            widget.item(widget.count() - 1).setData(_ID_ROLE, int(row.key))
        return widget

    @staticmethod
    def _selected_ids(widget: QListWidget) -> list[int]:
        return [item.data(_ID_ROLE) for item in widget.selectedItems()]

    def result_values(self) -> tuple[list[int], str, list[int], int, list[int]]:
        return (
            self._selected_ids(self._groups),
            self._subject.text().strip(),
            self._selected_ids(self._teachers),
            self._sessions.value(),
            self._selected_ids(self._rooms),
        )


class DataManagerModule(QWidget):
    """Editor tabular de las entidades del proyecto con CRUD y carga horaria."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._tables: EntityTables | None = None
        self._tabs = QTabWidget()
        self._views: dict[str, QTableView] = {}

        add_btn = QPushButton("Añadir")
        add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton("Eliminar")
        del_btn.clicked.connect(self._on_delete)
        load_btn = QPushButton("Añadir carga (clase)…")
        load_btn.clicked.connect(self._on_add_load)
        toolbar = QHBoxLayout()
        toolbar.addWidget(add_btn)
        toolbar.addWidget(del_btn)
        toolbar.addWidget(load_btn)
        toolbar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._tabs)
        bridge.session_changed.connect(self.refresh)

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        current = self._tabs.currentIndex()
        self._tables = self._bridge.tables()
        self._tabs.clear()
        self._views.clear()
        for table in self._tables.as_tuple():
            view = QTableView()
            view.setModel(self._model_for(table))
            view.setAlternatingRowColors(True)
            view.verticalHeader().setVisible(False)
            view.resizeColumnsToContents()
            view.horizontalHeader().setStretchLastSection(True)
            view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
            self._tabs.addTab(view, f"{table.title} ({len(table.rows)})")
            self._views[table.kind] = view
        if 0 <= current < self._tabs.count():
            self._tabs.setCurrentIndex(current)

    def _current_kind(self) -> str:
        index = self._tabs.currentIndex()
        return _KINDS[index] if 0 <= index < len(_KINDS) else "teacher"

    def _selected_key(self) -> str | None:
        view = self._views.get(self._current_kind())
        if view is None:
            return None
        rows = view.selectionModel().selectedRows()
        if not rows or self._tables is None:
            return None
        table = {t.kind: t for t in self._tables.as_tuple()}[self._current_kind()]
        row = rows[0].row()
        return table.rows[row].key if 0 <= row < len(table.rows) else None

    # --- CRUD ----------------------------------------------------------- #
    def _on_add(self) -> None:
        kind = self._current_kind()
        try:
            if kind == "teacher":
                name, ok = QInputDialog.getText(self, "Nuevo docente", "Nombre:")
                if ok and name.strip():
                    self._bridge.add_teacher(name)
            elif kind == "group":
                name, ok = QInputDialog.getText(self, "Nuevo grupo", "Nombre:")
                if ok and name.strip():
                    size, ok2 = QInputDialog.getInt(self, "Nuevo grupo", "Tamaño:", 30, 1, 300)
                    if ok2:
                        self._bridge.add_group(name, size)
            elif kind == "room":
                name, ok = QInputDialog.getText(self, "Nueva aula", "Nombre:")
                if ok and name.strip():
                    seats, ok2 = QInputDialog.getInt(self, "Nueva aula", "Cupos:", 30, 1, 300)
                    if ok2:
                        self._bridge.add_room(name, seats)
            else:
                self._on_add_load()  # las materias se crean con la carga
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo añadir", str(exc))

    def _on_delete(self) -> None:
        kind = self._current_kind()
        key = self._selected_key()
        if key is None:
            QMessageBox.information(self, "Eliminar", "Selecciona una fila primero.")
            return
        if (
            QMessageBox.question(
                self, "Eliminar", "¿Eliminar el elemento seleccionado y sus clases?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            if kind == "subject":
                self._bridge.remove_subject(key)
            else:
                self._bridge.remove_resource(int(key))
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo eliminar", str(exc))

    def _on_add_load(self) -> None:
        if self._tables is None:
            return
        if not self._tables.groups.rows or not self._tables.teachers.rows:
            QMessageBox.information(self, "Carga", "Necesitas al menos un grupo y un docente.")
            return
        dialog = _LoadDialog(self._tables, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        group_ids, subject, teacher_ids, sessions, room_ids = dialog.result_values()
        if not subject or not group_ids or not teacher_ids:
            QMessageBox.information(
                self, "Carga", "Indica materia, al menos un grupo y un docente."
            )
            return
        try:
            self._bridge.add_load(group_ids, subject, teacher_ids, sessions, room_ids or None)
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo añadir la carga", str(exc))

    # --- modelos / edición ---------------------------------------------- #
    def _model_for(self, table: EntityTable) -> EntityTableModel:
        if table.kind == "teacher":
            return EntityTableModel(
                table, editable=frozenset({_NAME_COL}), on_edit=self._edit_resource
            )
        if table.kind == "group":
            return EntityTableModel(
                table, editable=frozenset({_NAME_COL, 2}), on_edit=self._edit_group
            )
        if table.kind == "room":
            return EntityTableModel(
                table, editable=frozenset({_NAME_COL, 2}), on_edit=self._edit_room
            )
        return EntityTableModel(table)  # materias: solo lectura (se editan por carga)

    def _edit_resource(self, key: str, column: int, value: str) -> bool:
        value = value.strip()
        if column == _NAME_COL and value:
            return self._bridge.rename_resource(int(key), value)
        return False

    def _edit_group(self, key: str, column: int, value: str) -> bool:
        if column == _NAME_COL:
            return self._edit_resource(key, column, value)
        if column == 2:  # tamaño
            try:
                size = int(value)
            except ValueError:
                return False
            return size >= 1 and self._bridge.set_group_size(int(key), size)
        return False

    def _edit_room(self, key: str, column: int, value: str) -> bool:
        if column == _NAME_COL:
            return self._edit_resource(key, column, value)
        if column == 2:  # cupos
            try:
                seats = int(value)
            except ValueError:
                return False
            return seats >= 1 and self._bridge.set_room_seats(int(key), seats)
        return False
