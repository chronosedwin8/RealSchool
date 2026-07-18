"""Módulo 3 · Data Manager: datos maestros estilo Untis.

Pestañas Docentes/Aulas/Grupos/Materias como las ventanas de datos de Untis:
**Abreviatura + Nombre completo** y los campos de cada entidad. Se edita como en
Excel: clic o teclear sobre la celda; la **fila vacía del final crea un registro
nuevo** al escribir su abreviatura. El Color de la materia abre la paleta. La
carga horaria se ingresa en la ventana **Carga (lecciones)**.

Robustez: las vistas se crean una sola vez y los refrescos por señal se difieren
al siguiente ciclo del event loop (nunca se reconstruye la tabla mientras un
editor de celda sigue confirmando: eso reventaba la interfaz).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import ConfigError, EntityTable, EntityTables

from ..engine_bridge import EngineBridge
from ..models import EntityTableModel

_KINDS = ("teacher", "room", "group", "subject")
_TITLES = {"teacher": "Docentes", "room": "Aulas", "group": "Grupos", "subject": "Materias"}
#: Columnas calculadas por el motor (no editables).
_READONLY_FIELDS = {"classes", "availability", "sessions", "teachers"}
_EXCEL_TRIGGERS = (
    QAbstractItemView.EditTrigger.DoubleClicked
    | QAbstractItemView.EditTrigger.SelectedClicked
    | QAbstractItemView.EditTrigger.EditKeyPressed
    | QAbstractItemView.EditTrigger.AnyKeyPressed
)


class DataManagerModule(QWidget):
    """Ventanas de datos maestros (docentes/aulas/grupos/materias), estilo Untis."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._tables: EntityTables | None = None
        self._tabs = QTabWidget()
        self._views: dict[str, QTableView] = {}
        self._models: dict[str, EntityTableModel] = {}
        self._refresh_pending = False

        # Selector de registro (como el combo superior de Untis).
        self._record = QComboBox()
        self._record.setMinimumWidth(180)
        self._record.activated.connect(self._jump_to_record)

        self._add_btn = QPushButton("Nuevo")
        self._add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton("Eliminar")
        del_btn.clicked.connect(self._on_delete)
        self._hint = QLabel(
            "Escribe en la última fila (*) para crear · clic en una celda para editar."
        )
        self._hint.setStyleSheet("color: #64748b;")
        toolbar = QHBoxLayout()
        toolbar.addWidget(self._record)
        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(del_btn)
        toolbar.addWidget(self._hint)
        toolbar.addStretch(1)

        # Las vistas se crean UNA vez; cada refresco solo cambia el modelo.
        for kind in _KINDS:
            view = QTableView()
            view.setAlternatingRowColors(True)
            view.verticalHeader().setVisible(False)
            view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
            view.setEditTriggers(_EXCEL_TRIGGERS)
            view.doubleClicked.connect(lambda index, k=kind: self._maybe_pick_color(k, index))
            self._tabs.addTab(view, _TITLES[kind])
            self._views[kind] = view

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._tabs)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        bridge.session_refreshed.connect(self._defer_refresh)

    # --- refresco seguro (fuera del commit del editor) ------------------- #
    def _defer_refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._do_deferred_refresh)

    def _do_deferred_refresh(self) -> None:
        self._refresh_pending = False
        self.refresh()

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        self._tables = self._bridge.tables()
        for i, kind in enumerate(_KINDS):
            table = self._table_of(kind)
            if table is None:
                continue
            model = self._model_for(table)
            self._models[kind] = model
            view = self._views[kind]
            view.setModel(model)
            view.resizeColumnsToContents()
            view.horizontalHeader().setStretchLastSection(True)
            self._tabs.setTabText(i, f"{table.title} ({len(table.rows)})")
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
    def _creator_for(self, kind: str) -> Callable[[str], bool]:
        def create(name: str) -> bool:
            try:
                if kind == "teacher":
                    self._bridge.add_teacher(name)
                elif kind == "room":
                    self._bridge.add_room(name, 30)
                elif kind == "group":
                    self._bridge.add_group(name, 30)
                else:
                    self._bridge.add_subject(name)
                return True
            except ConfigError:
                return False

        return create

    def _on_add(self) -> None:
        kind = self._current_kind()
        if not self._creator_for(kind)(self._default_name(_TITLES[kind][:-1].upper())):
            QMessageBox.warning(self, "No se pudo añadir", "Revisa los datos e inténtalo de nuevo.")
            return
        self.refresh()
        self._edit_last_row(kind)

    def _edit_last_row(self, kind: str) -> None:
        view = self._views.get(kind)
        table = self._table_of(kind)
        model = self._models.get(kind)
        if view is None or table is None or model is None or not table.rows:
            return
        index = model.index(len(table.rows) - 1, 0)
        view.setCurrentIndex(index)
        view.scrollTo(index)
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

    # --- modelos / edición en celda -------------------------------------- #
    def _model_for(self, table: EntityTable) -> EntityTableModel:
        editable = frozenset(
            i
            for i, field in enumerate(table.fields)
            if field not in _READONLY_FIELDS and field != "color"
        )

        def on_edit(key: str, col: int, val: str, *, _table: EntityTable = table) -> bool:
            return self._on_cell_edit(_table.kind, _table, key, col, val)

        return EntityTableModel(
            table, editable=editable, on_edit=on_edit, on_create=self._creator_for(table.kind)
        )

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
        if index.row() >= len(table.rows):
            return  # fila vacía de alta
        if index.column() >= len(table.fields) or table.fields[index.column()] != "color":
            return
        row = table.rows[index.row()]
        color = QColorDialog.getColor(parent=self, title=f"Color de {row.cells[0]}")
        if color.isValid():
            self._bridge.set_subject_info(row.key, "color", color.name())
