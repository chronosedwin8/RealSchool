"""Módulo 3 · Data Manager: ingreso de datos del proyecto (tablas editables).

Pestañas Docentes/Aulas/Grupos/Materias como DataGrids: **Añadir** crea una fila
nueva con un nombre por defecto lista para editar en la propia tabla (doble-clic),
**Eliminar** quita la seleccionada, y las celdas se editan en sitio. La carga
horaria (clases) se ingresa aparte, con estos datos ya cargados. Todo enruta a la
Fachada; la UI no valida reglas.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
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

_KINDS = ("teacher", "room", "group", "subject")
_ID_ROLE = int(Qt.ItemDataRole.UserRole)
# Columna del nombre y columnas editables adicionales, por tipo.
_NAME_COL = {"teacher": 1, "room": 1, "group": 1, "subject": 0}


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
            widget.addItem(row.cells[1] if len(row.cells) > 1 else row.cells[0])
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
    """Ingreso y edición de las entidades del proyecto (docentes/aulas/grupos/materias)."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._tables: EntityTables | None = None
        self._tabs = QTabWidget()
        self._views: dict[str, QTableView] = {}

        self._add_btn = QPushButton("+ Añadir")
        self._add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton("Eliminar")
        del_btn.clicked.connect(self._on_delete)
        load_btn = QPushButton("Añadir carga (clase)…")
        load_btn.clicked.connect(self._on_add_load)
        self._hint = QLabel("Doble-clic en una celda para editar.")
        self._hint.setStyleSheet("color: #64748b;")
        toolbar = QHBoxLayout()
        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(del_btn)
        toolbar.addWidget(load_btn)
        toolbar.addWidget(self._hint)
        toolbar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._tabs)
        self._tabs.currentChanged.connect(self._update_add_label)
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
        self._update_add_label()

    def _current_kind(self) -> str:
        index = self._tabs.currentIndex()
        return _KINDS[index] if 0 <= index < len(_KINDS) else "teacher"

    def _update_add_label(self) -> None:
        label = {
            "teacher": "+ Añadir docente",
            "room": "+ Añadir aula",
            "group": "+ Añadir grupo",
            "subject": "+ Añadir materia",
        }
        self._add_btn.setText(label.get(self._current_kind(), "+ Añadir"))

    def _table_of(self, kind: str) -> EntityTable | None:
        if self._tables is None:
            return None
        return {t.kind: t for t in self._tables.as_tuple()}.get(kind)

    def _selected_key(self) -> str | None:
        view = self._views.get(self._current_kind())
        table = self._table_of(self._current_kind())
        if view is None or table is None:
            return None
        rows = view.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return table.rows[row].key if 0 <= row < len(table.rows) else None

    def _default_name(self, base: str) -> str:
        existing = set()
        table = self._table_of(self._current_kind())
        if table is not None:
            col = _NAME_COL[self._current_kind()]
            existing = {r.cells[col] for r in table.rows}
        n = 1
        while f"{base} {n}" in existing:
            n += 1
        return f"{base} {n}"

    # --- alta / baja ---------------------------------------------------- #
    def _on_add(self) -> None:
        kind = self._current_kind()
        try:
            if kind == "teacher":
                self._bridge.add_teacher(self._default_name("Docente"))
            elif kind == "room":
                self._bridge.add_room(self._default_name("Aula"), 30)
            elif kind == "group":
                self._bridge.add_group(self._default_name("Grupo"), 30)
            else:
                self._bridge.add_subject(self._default_name("Materia"))
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo añadir", str(exc))
            return
        self._edit_last_row(kind)

    def _edit_last_row(self, kind: str) -> None:
        view = self._views.get(kind)
        model = view.model() if view is not None else None
        if view is None or model is None or model.rowCount() == 0:
            return
        index = model.index(model.rowCount() - 1, _NAME_COL[kind])
        view.setCurrentIndex(index)
        view.scrollToBottom()
        view.edit(index)

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

    # --- modelos / edición en celda ------------------------------------- #
    def _model_for(self, table: EntityTable) -> EntityTableModel:
        if table.kind == "teacher":
            return EntityTableModel(table, editable=frozenset({1}), on_edit=self._edit_resource)
        if table.kind == "group":
            return EntityTableModel(table, editable=frozenset({1, 2}), on_edit=self._edit_group)
        if table.kind == "room":
            return EntityTableModel(table, editable=frozenset({1, 2}), on_edit=self._edit_room)
        return EntityTableModel(table, editable=frozenset({0}), on_edit=self._edit_subject)

    def _edit_resource(self, key: str, column: int, value: str) -> bool:
        value = value.strip()
        return bool(value) and self._bridge.rename_resource(int(key), value)

    def _edit_group(self, key: str, column: int, value: str) -> bool:
        if column == 1:
            return self._edit_resource(key, column, value)
        try:
            size = int(value)
        except ValueError:
            return False
        return size >= 1 and self._bridge.set_group_size(int(key), size)

    def _edit_room(self, key: str, column: int, value: str) -> bool:
        if column == 1:
            return self._edit_resource(key, column, value)
        try:
            seats = int(value)
        except ValueError:
            return False
        return seats >= 1 and self._bridge.set_room_seats(int(key), seats)

    def _edit_subject(self, key: str, column: int, value: str) -> bool:
        value = value.strip()
        if not value or value == key:
            return False
        try:
            return self._bridge.rename_subject(key, value)
        except ConfigError:
            return False
