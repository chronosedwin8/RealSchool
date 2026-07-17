"""Módulo · Carga (lecciones): el ingreso de carga horaria como en Untis.

Se elige **un grupo o un docente** y se ve su carga
(``N.lec | HHs | Profesores | Materia | Grupo(s) | Aulas``). Se edita **como en
Excel**: HHs y Materia directamente en la celda; doble-clic en Profesores,
Grupo(s) o Aulas abre su selector múltiple. Los **acoples** (clases simultáneas:
varios profesores en varios salones, misma materia o distintas) se muestran como
fila padre + sub-filas (↳), igual que Untis: selecciona varias lecciones y pulsa
*Acoplar*. Todo se enruta a la Fachada.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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
_TEACHERS_COL = 2
_SUBJECT_COL = 3
_GROUPS_COL = 4
_ROOMS_COL = 5
_EDITABLE_COLS = {_HHS_COL, _SUBJECT_COL}


class _MultiPickDialog(QDialog):
    """Selector múltiple de una entidad (docentes, grupos o aulas)."""

    def __init__(
        self,
        table: EntityTable,
        parent: QWidget,
        *,
        title: str,
        info: str,
        preselect: tuple[int, ...] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        label = QLabel(info)
        label.setWordWrap(True)
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for row in table.rows:
            text = row.cells[0]
            if len(row.cells) > 1 and row.cells[1]:
                text = f"{row.cells[0]} — {row.cells[1]}"
            self._list.addItem(text)
            item = self._list.item(self._list.count() - 1)
            item.setData(_ID_ROLE, int(row.key))
            if int(row.key) in preselect:
                item.setSelected(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self._list)
        layout.addWidget(buttons)

    def selected(self) -> list[int]:
        return [item.data(_ID_ROLE) for item in self._list.selectedItems()]


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
        self._refresh_pending = False

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
        couple_btn = QPushButton("Acoplar")
        couple_btn.setToolTip("Selecciona 2+ lecciones: ocurrirán a la misma hora")
        couple_btn.clicked.connect(self._on_couple)
        uncouple_btn = QPushButton("Desacoplar")
        uncouple_btn.clicked.connect(self._on_uncouple)
        self._total = QLabel("HHs: 0")
        self._total.setStyleSheet("font-weight: 700;")
        hint = QLabel("Edita HHs y Materia en la celda · doble-clic en Profesores/Grupos/Aulas.")
        hint.setStyleSheet("color: #64748b;")

        top = QHBoxLayout()
        top.addWidget(QLabel("Ver por:"))
        top.addWidget(self._mode)
        top.addWidget(self._record)
        top.addWidget(new_btn)
        top.addWidget(del_btn)
        top.addWidget(couple_btn)
        top.addWidget(uncouple_btn)
        top.addWidget(self._total)
        top.addWidget(hint)
        top.addStretch(1)

        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellDoubleClicked.connect(self._on_cell_double)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._table, stretch=1)

        bridge.session_changed.connect(self._defer_refresh)

    # --- refresco seguro (fuera del commit del editor) ------------------- #
    def _defer_refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._do_deferred_refresh)

    def _do_deferred_refresh(self) -> None:
        self._refresh_pending = False
        self.refresh()

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
        prev_coupling = -1
        for i, row in enumerate(self._rows):
            is_sub = row.coupling_id >= 0 and row.coupling_id == prev_coupling
            marker = "↳" if is_sub else ("⛓ " if row.coupling_id >= 0 else "")
            cells = (
                f"{marker}{'' if is_sub else row.task_ids[0]}",
                str(row.hours),
                ", ".join(row.teachers),
                row.subject,
                ", ".join(row.groups),
                ", ".join(row.rooms) if row.rooms else "(el motor elige)",
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col not in _EDITABLE_COLS:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, col, item)
            prev_coupling = row.coupling_id if row.coupling_id >= 0 else -1
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setStretchLastSection(True)
        self._loading = False
        self._total.setText(f"HHs: {sum(r.hours for r in self._rows)}")

    # --- acciones -------------------------------------------------------- #
    def _selected_lessons(self) -> list[LessonRow]:
        rows = sorted({index.row() for index in self._table.selectionModel().selectedRows()})
        return [self._rows[r] for r in rows if 0 <= r < len(self._rows)]

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
        selected = self._selected_lessons()
        if not selected:
            QMessageBox.information(self, "Eliminar", "Selecciona una lección primero.")
            return
        lesson = selected[0]
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

    def _on_couple(self) -> None:
        selected = self._selected_lessons()
        if len(selected) < 2:
            QMessageBox.information(
                self,
                "Acoplar",
                "Selecciona dos o más lecciones (Ctrl+clic) para que ocurran a la misma hora.",
            )
            return
        try:
            self._bridge.couple_lessons([list(lesson.task_ids) for lesson in selected])
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo acoplar", str(exc))

    def _on_uncouple(self) -> None:
        selected = self._selected_lessons()
        if not selected:
            QMessageBox.information(self, "Desacoplar", "Selecciona una lección acoplada.")
            return
        try:
            self._bridge.uncouple_lesson(list(selected[0].task_ids))
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo desacoplar", str(exc))

    # --- edición en celda / doble-clic ----------------------------------- #
    def _on_cell_double(self, row: int, column: int) -> None:
        if not 0 <= row < len(self._rows):
            return
        lesson = self._rows[row]
        tables = self._bridge.tables()
        try:
            if column == _ROOMS_COL:
                dialog = _MultiPickDialog(
                    tables.rooms,
                    self,
                    title="Aulas de la lección",
                    info="Marca una o varias aulas fijas. Sin selección = el motor elige.",
                    preselect=lesson.room_ids,
                )
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    self._bridge.set_lesson_rooms(list(lesson.task_ids), dialog.selected())
            elif column == _TEACHERS_COL:
                dialog = _MultiPickDialog(
                    tables.teachers,
                    self,
                    title="Docentes de la lección",
                    info="Marca uno o varios docentes (co-docencia).",
                    preselect=lesson.teacher_ids,
                )
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    self._bridge.set_lesson_teachers(list(lesson.task_ids), dialog.selected())
            elif column == _GROUPS_COL:
                dialog = _MultiPickDialog(
                    tables.groups,
                    self,
                    title="Grupos de la lección",
                    info="Marca uno o varios grupos (clases combinadas).",
                    preselect=lesson.group_ids,
                )
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    self._bridge.set_lesson_groups(list(lesson.task_ids), dialog.selected())
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo aplicar el cambio", str(exc))

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        if not 0 <= row < len(self._rows):
            return
        lesson = self._rows[row]
        if item.column() == _HHS_COL:
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
        elif item.column() == _SUBJECT_COL:
            subject = item.text().strip()
            if not subject or subject == lesson.subject:
                self._reload_grid()
                return
            try:
                self._bridge.set_lesson_subject(list(lesson.task_ids), subject)
            except ConfigError as exc:
                QMessageBox.warning(self, "Materia no válida", str(exc))
                self._reload_grid()
