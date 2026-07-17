"""Módulo 3 · Data Manager: datos maestros estilo Untis.

Pestañas Docentes/Aulas/Grupos/Materias como las ventanas de datos de Untis:
**Abreviatura + Nombre completo** y los campos de cada entidad (e-mail y sección
del docente; sección y aula propia del grupo; capacidad y aula alternativa del
aula; sección y **color** de la materia). Todo se edita **en la celda**; *Nuevo*
crea la fila lista para escribir; el selector de registro salta a una fila. La
UI no valida reglas: cada edición se enruta a la Fachada por su campo semántico.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
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
#: Columnas calculadas por el motor (no editables).
_READONLY_FIELDS = {"classes", "availability", "sessions", "teachers"}


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
            label = row.cells[0]
            if len(row.cells) > 1 and row.cells[1]:
                label = f"{row.cells[0]} — {row.cells[1]}"
            widget.addItem(label)
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
    """Ventanas de datos maestros (docentes/aulas/grupos/materias), estilo Untis."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._tables: EntityTables | None = None
        self._tabs = QTabWidget()
        self._views: dict[str, QTableView] = {}

        # Selector de registro (como el combo superior de Untis).
        self._record = QComboBox()
        self._record.setMinimumWidth(180)
        self._record.activated.connect(self._jump_to_record)

        self._add_btn = QPushButton("Nuevo")
        self._add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton("Eliminar")
        del_btn.clicked.connect(self._on_delete)
        load_btn = QPushButton("Añadir carga (clase)…")
        load_btn.clicked.connect(self._on_add_load)
        self._hint = QLabel(
            "Doble-clic en una celda para editar · en Materias, el Color abre la paleta."
        )
        self._hint.setStyleSheet("color: #64748b;")
        toolbar = QHBoxLayout()
        toolbar.addWidget(self._record)
        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(del_btn)
        toolbar.addWidget(load_btn)
        toolbar.addWidget(self._hint)
        toolbar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._tabs)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        bridge.session_changed.connect(self.refresh)

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        current = self._tabs.currentIndex()
        self._tables = self._bridge.tables()
        self._tabs.blockSignals(True)
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
            view.doubleClicked.connect(lambda index, k=table.kind: self._maybe_pick_color(k, index))
            self._tabs.addTab(view, f"{table.title} ({len(table.rows)})")
            self._views[table.kind] = view
        self._tabs.blockSignals(False)
        if 0 <= current < self._tabs.count():
            self._tabs.setCurrentIndex(current)
        self._on_tab_changed()

    # --- selector de registro y pestañas -------------------------------- #
    def _current_kind(self) -> str:
        index = self._tabs.currentIndex()
        return _KINDS[index] if 0 <= index < len(_KINDS) else "teacher"

    def _table_of(self, kind: str) -> EntityTable | None:
        if self._tables is None:
            return None
        return {t.kind: t for t in self._tables.as_tuple()}.get(kind)

    def _on_tab_changed(self) -> None:
        labels = {
            "teacher": "Nuevo docente",
            "room": "Nueva aula",
            "group": "Nuevo grupo",
            "subject": "Nueva materia",
        }
        self._add_btn.setText(labels.get(self._current_kind(), "Nuevo"))
        table = self._table_of(self._current_kind())
        self._record.clear()
        if table is not None:
            for i, row in enumerate(table.rows):
                self._record.addItem(row.cells[0], i)

    def _jump_to_record(self, index: int) -> None:
        view = self._views.get(self._current_kind())
        row = self._record.itemData(index)
        model = view.model() if view is not None else None
        if view is None or model is None or not isinstance(row, int):
            return
        view.selectRow(row)
        view.scrollTo(model.index(row, 0))

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
        existing: set[str] = set()
        table = self._table_of(self._current_kind())
        if table is not None:
            existing = {r.cells[0] for r in table.rows}
        n = 1
        while f"{base}{n}" in existing:
            n += 1
        return f"{base}{n}"

    # --- alta / baja ----------------------------------------------------- #
    def _on_add(self) -> None:
        kind = self._current_kind()
        try:
            if kind == "teacher":
                self._bridge.add_teacher(self._default_name("DOC"))
            elif kind == "room":
                self._bridge.add_room(self._default_name("AULA"), 30)
            elif kind == "group":
                self._bridge.add_group(self._default_name("GRUPO"), 30)
            else:
                self._bridge.add_subject(self._default_name("MAT"))
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo añadir", str(exc))
            return
        self._edit_last_row(kind)

    def _edit_last_row(self, kind: str) -> None:
        view = self._views.get(kind)
        model = view.model() if view is not None else None
        if view is None or model is None or model.rowCount() == 0:
            return
        index = model.index(model.rowCount() - 1, 0)
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

    # --- modelos / edición en celda -------------------------------------- #
    def _model_for(self, table: EntityTable) -> EntityTableModel:
        editable = frozenset(
            i
            for i, field in enumerate(table.fields)
            if field not in _READONLY_FIELDS and field != "color"
        )

        def on_edit(key: str, col: int, val: str, *, _table: EntityTable = table) -> bool:
            return self._on_cell_edit(_table.kind, _table, key, col, val)

        return EntityTableModel(table, editable=editable, on_edit=on_edit)

    def _on_cell_edit(
        self, kind: str, table: EntityTable, key: str, column: int, value: str
    ) -> bool:
        field = table.fields[column] if column < len(table.fields) else ""
        value = value.strip()
        try:
            if field == "abbrev":
                if not value:
                    return False
                if kind == "subject":
                    return self._bridge.rename_subject(key, value)
                return self._bridge.rename_resource(int(key), value)
            if field == "seats":
                seats = int(value)
                return seats >= 1 and self._bridge.set_room_seats(int(key), seats)
            if field == "size":
                size = int(value)
                return size >= 1 and self._bridge.set_group_size(int(key), size)
            if kind == "subject":
                return self._bridge.set_subject_info(key, field, value)
            return self._bridge.set_resource_info(int(key), field, value)
        except ConfigError, ValueError:
            return False

    def _maybe_pick_color(self, kind: str, index: QModelIndex) -> None:
        table = self._table_of(kind)
        if table is None or kind != "subject" or not index.isValid():
            return
        if index.column() >= len(table.fields) or table.fields[index.column()] != "color":
            return
        row = table.rows[index.row()]
        color = QColorDialog.getColor(parent=self, title=f"Color de {row.cells[0]}")
        if color.isValid():
            self._bridge.set_subject_info(row.key, "color", color.name())
