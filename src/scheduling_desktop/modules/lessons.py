"""Módulo · Carga (lecciones): el ingreso de carga horaria como en Untis.

La ventana de lecciones de Untis: se elige **un grupo o un docente** y se ven sus
lecciones (``N.lec | HHs | Profesores | Materia | Grupo(s) | Aulas``). *Nueva
lección* abre un formulario con la materia (de las dadas de alta), los docentes,
grupos y aulas (multi-selección: co-docencia y clases combinadas), pre-marcando
el registro actual. Las **HHs se editan en la celda**; *Eliminar* borra la
lección completa. Todo se enruta a la Fachada.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import ConfigError, EntityTable, LessonRow

from ..engine_bridge import EngineBridge

_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_COLUMNS = ("N.lec", "HHs", "Profesores", "Materia", "Grupo(s)", "Aulas")
_HHS_COL = 1


class _LessonDialog(QDialog):
    """Formulario de lección nueva, pre-marcando el grupo o docente actual."""

    def __init__(
        self,
        bridge: EngineBridge,
        parent: QWidget,
        *,
        preselect_group: int | None = None,
        preselect_teacher: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nueva lección")
        tables = bridge.tables()

        self._subject = QComboBox()
        self._subject.setEditable(True)
        for row in tables.subjects.rows:
            self._subject.addItem(row.cells[0])
        self._subject.setCurrentText("")

        self._sessions = QSpinBox()
        self._sessions.setRange(1, 40)

        self._teachers = self._multi_list(tables.teachers, preselect_teacher)
        self._groups = self._multi_list(tables.groups, preselect_group)
        self._rooms = self._multi_list(tables.rooms, None)

        form = QFormLayout()
        form.addRow("Materia:", self._subject)
        form.addRow("HHs (sesiones/semana):", self._sessions)
        form.addRow(QLabel("Docentes:"), self._teachers)
        form.addRow(QLabel("Grupo(s):"), self._groups)
        form.addRow(QLabel("Aulas (vacío = el motor elige):"), self._rooms)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _multi_list(table: EntityTable, preselect: int | None) -> QListWidget:
        widget = QListWidget()
        widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        widget.setMaximumHeight(110)
        for row in table.rows:
            label = row.cells[0]
            if len(row.cells) > 1 and row.cells[1]:
                label = f"{row.cells[0]} — {row.cells[1]}"
            widget.addItem(label)
            item = widget.item(widget.count() - 1)
            item.setData(_ID_ROLE, int(row.key))
            if preselect is not None and int(row.key) == preselect:
                item.setSelected(True)
        return widget

    @staticmethod
    def _selected(widget: QListWidget) -> list[int]:
        return [item.data(_ID_ROLE) for item in widget.selectedItems()]

    def values(self) -> tuple[str, int, list[int], list[int], list[int]]:
        return (
            self._subject.currentText().strip(),
            self._sessions.value(),
            self._selected(self._teachers),
            self._selected(self._groups),
            self._selected(self._rooms),
        )


class LessonsModule(QWidget):
    """Ventana de lecciones por grupo o por docente (ingreso de la carga)."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._rows: tuple[LessonRow, ...] = ()
        self._loading = False

        self._mode = QComboBox()
        self._mode.addItem("Grupos", "group")
        self._mode.addItem("Docentes", "teacher")
        self._mode.currentIndexChanged.connect(self._reload_records)

        self._record = QComboBox()
        self._record.setMinimumWidth(160)
        self._record.currentIndexChanged.connect(self._reload_grid)

        new_btn = QPushButton("Nueva lección…")
        new_btn.clicked.connect(self._on_new)
        del_btn = QPushButton("Eliminar")
        del_btn.clicked.connect(self._on_delete)
        self._total = QLabel("HHs: 0")
        self._total.setStyleSheet("font-weight: 700;")
        hint = QLabel("Doble-clic en HHs para cambiar las horas semanales.")
        hint.setStyleSheet("color: #64748b;")

        top = QHBoxLayout()
        top.addWidget(QLabel("Ver por:"))
        top.addWidget(self._mode)
        top.addWidget(self._record)
        top.addWidget(new_btn)
        top.addWidget(del_btn)
        top.addWidget(self._total)
        top.addWidget(hint)
        top.addStretch(1)

        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.itemChanged.connect(self._on_item_changed)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._table, stretch=1)

        bridge.session_changed.connect(self.refresh)

    # --- selección de registro ------------------------------------------ #
    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        self._reload_records()

    def _reload_records(self) -> None:
        if not self._bridge.has_session:
            return
        tables = self._bridge.tables()
        source = tables.groups if self._mode.currentData() == "group" else tables.teachers
        previous = self._record.currentData()
        self._record.blockSignals(True)
        self._record.clear()
        for row in source.rows:
            self._record.addItem(row.cells[0], int(row.key))
        index = self._record.findData(previous)
        self._record.setCurrentIndex(index if index >= 0 else 0)
        self._record.blockSignals(False)
        self._reload_grid()

    def _reload_grid(self) -> None:
        record = self._record.currentData()
        if not self._bridge.has_session or not isinstance(record, int):
            self._rows = ()
            self._table.setRowCount(0)
            self._total.setText("HHs: 0")
            return
        if self._mode.currentData() == "group":
            self._rows = self._bridge.lessons(group_id=record)
        else:
            self._rows = self._bridge.lessons(teacher_id=record)
        self._loading = True
        self._table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            cells = (
                str(row.task_ids[0]),
                str(row.hours),
                ", ".join(row.teachers),
                row.subject,
                ", ".join(row.groups),
                ", ".join(row.rooms) if row.rooms else "(el motor elige)",
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col != _HHS_COL:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, col, item)
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setStretchLastSection(True)
        self._loading = False
        self._total.setText(f"HHs: {sum(r.hours for r in self._rows)}")

    # --- acciones -------------------------------------------------------- #
    def _on_new(self) -> None:
        if not self._bridge.has_session:
            return
        record = self._record.currentData()
        preselect_group = record if self._mode.currentData() == "group" else None
        preselect_teacher = record if self._mode.currentData() == "teacher" else None
        dialog = _LessonDialog(
            self._bridge,
            self,
            preselect_group=preselect_group if isinstance(preselect_group, int) else None,
            preselect_teacher=preselect_teacher if isinstance(preselect_teacher, int) else None,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        subject, sessions, teachers, groups, rooms = dialog.values()
        if not subject or not teachers or not groups:
            QMessageBox.information(
                self, "Lección", "Indica materia y al menos un docente y un grupo."
            )
            return
        try:
            self._bridge.add_load(groups, subject, teachers, sessions, rooms or None)
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo crear la lección", str(exc))

    def _on_delete(self) -> None:
        row = self._table.currentRow()
        if not 0 <= row < len(self._rows):
            QMessageBox.information(self, "Eliminar", "Selecciona una lección primero.")
            return
        lesson = self._rows[row]
        if (
            QMessageBox.question(
                self,
                "Eliminar lección",
                f"¿Eliminar {lesson.subject} ({lesson.hours} HHs) de {', '.join(lesson.groups)}?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._bridge.remove_lesson(list(lesson.task_ids))
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo eliminar", str(exc))

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != _HHS_COL:
            return
        row = item.row()
        if not 0 <= row < len(self._rows):
            return
        lesson = self._rows[row]
        try:
            hours = int(item.text())
        except ValueError:
            self._reload_grid()
            return
        if hours == lesson.hours:
            return
        try:
            self._bridge.set_lesson_hours(list(lesson.task_ids), hours)
        except ConfigError as exc:
            QMessageBox.warning(self, "HHs no válidas", str(exc))
            self._reload_grid()
