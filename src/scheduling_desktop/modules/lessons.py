"""Módulo · Carga (lecciones): el ingreso de carga horaria como en Untis.

Se elige **un grupo o un docente** y se ve su carga
(``N.lec | HHs | Profesores | Materia | Grupo(s) | Aulas``). Se ingresa **como
en Excel**: la **fila vacía (*) del final crea la lección** — escribe la Materia
y las HHs en la celda y elige docentes/grupos/aulas con doble-clic (el grupo o
docente actual viene pre-cargado). Los **acoples** (clases simultáneas: varios
profesores en varios salones, misma materia o distintas) se muestran como en
Untis: una fila con **⊞ (nGrupos, nProfesores)** que se expande a sub-filas.
Todo se enruta a la Fachada.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
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
_PLACEHOLDER = QColor("#94a3b8")


@dataclass
class _Pending:
    """La lección en construcción de la fila vacía (estilo Excel)."""

    subject: str = ""
    hours: int = 1
    teachers: list[int] = field(default_factory=list)
    groups: list[int] = field(default_factory=list)
    rooms: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class _DisplayRow:
    """Una fila visible: lección + tipo (single/parent/sub) + conteos del acople."""

    lesson: LessonRow
    kind: str  # "single" | "parent" | "sub"
    n_groups: int = 0
    n_teachers: int = 0


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
    """Formulario de lección nueva (alternativa a la fila vacía)."""

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
        self._display: list[_DisplayRow] = []
        self._expanded: set[int] = set()
        self._pending = _Pending()
        self._loading = False
        self._refresh_pending = False

        self._mode = QComboBox()
        self._mode.addItem("Grupos", "group")
        self._mode.addItem("Docentes", "teacher")
        self._mode.currentIndexChanged.connect(self._reload_records)

        self._record = QComboBox()
        self._record.setMinimumWidth(160)
        self._record.currentIndexChanged.connect(self._on_record_changed)

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
        hint = QLabel("Escribe en la fila (*) para crear · clic en ⊞ expande el acople.")
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
        self._table.cellClicked.connect(self._on_cell_clicked)

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
        self._on_record_changed()

    def _on_record_changed(self) -> None:
        self._reset_pending()
        self._reload_grid()

    def _reset_pending(self) -> None:
        self._pending = _Pending()
        record = self._record.currentData()
        if isinstance(record, int):
            if self._mode.currentData() == "group":
                self._pending.groups = [record]
            else:
                self._pending.teachers = [record]

    # --- construcción de la vista (acoples colapsables) ------------------ #
    def _build_display(self, rows: tuple[LessonRow, ...]) -> list[_DisplayRow]:
        display: list[_DisplayRow] = []
        seen_couplings: set[int] = set()
        for row in rows:
            if row.coupling_id < 0:
                display.append(_DisplayRow(row, "single"))
                continue
            if row.coupling_id in seen_couplings:
                continue
            seen_couplings.add(row.coupling_id)
            cluster = [x for x in rows if x.coupling_id == row.coupling_id]
            n_groups = len({g for x in cluster for g in x.group_ids})
            n_teachers = len({t for x in cluster for t in x.teacher_ids})
            display.append(_DisplayRow(cluster[0], "parent", n_groups, n_teachers))
            if row.coupling_id in self._expanded:
                display.extend(_DisplayRow(x, "sub") for x in cluster[1:])
        return display

    def _reload_grid(self) -> None:
        record = self._record.currentData()
        if not self._bridge.has_session or not isinstance(record, int):
            self._display = []
            self._table.setRowCount(0)
            self._total.setText("HHs: 0")
            return
        if self._mode.currentData() == "group":
            rows = self._bridge.lessons(group_id=record)
        else:
            rows = self._bridge.lessons(teacher_id=record)
        self._display = self._build_display(rows)
        self._loading = True
        self._table.setRowCount(len(self._display) + 1)  # + fila vacía de alta
        for i, entry in enumerate(self._display):
            lesson = entry.lesson
            if entry.kind == "parent":
                mark = "⊟" if lesson.coupling_id in self._expanded else "⊞"
                nlec = f"{mark} {lesson.task_ids[0]}  ({entry.n_groups},{entry.n_teachers})"
            elif entry.kind == "sub":
                nlec = ""
            else:
                nlec = str(lesson.task_ids[0])
            cells = (
                nlec,
                "" if entry.kind == "sub" else str(lesson.hours),
                ", ".join(lesson.teachers),
                lesson.subject,
                ", ".join(lesson.groups),
                ", ".join(lesson.rooms) if lesson.rooms else "(el motor elige)",
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                editable = col == _SUBJECT_COL or (col == _HHS_COL and entry.kind != "sub")
                if not editable:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, col, item)
        self._render_blank_row(len(self._display))
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setStretchLastSection(True)
        self._loading = False
        seen: set[str] = set()
        total = 0
        for entry in self._display:
            if entry.lesson.key not in seen:
                seen.add(entry.lesson.key)
                total += entry.lesson.hours
        self._total.setText(f"HHs: {total}")

    def _render_blank_row(self, row: int) -> None:
        """La fila (*) de alta: se escribe/elige en ella y la lección se crea."""
        names = self._names_of
        cells = (
            "*",
            str(self._pending.hours),
            names("teacher", self._pending.teachers) or "(doble-clic: docentes)",
            self._pending.subject,
            names("group", self._pending.groups) or "(doble-clic: grupos)",
            names("room", self._pending.rooms) or "(el motor elige)",
        )
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if col in (_HHS_COL, _SUBJECT_COL):
                pass  # editable
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if text.startswith("(") or col == 0:
                item.setForeground(_PLACEHOLDER)
            self._table.setItem(row, col, item)

    def _names_of(self, kind: str, ids: list[int]) -> str:
        tables = self._bridge.tables()
        table = {"teacher": tables.teachers, "group": tables.groups, "room": tables.rooms}[kind]
        by_id = {int(r.key): r.cells[0] for r in table.rows}
        return ", ".join(by_id[i] for i in ids if i in by_id)

    def _try_create_pending(self) -> None:
        p = self._pending
        if not p.subject or not p.teachers or not p.groups:
            faltan = []
            if not p.subject:
                faltan.append("materia")
            if not p.teachers:
                faltan.append("docentes")
            if not p.groups:
                faltan.append("grupos")
            self._bridge.status_message.emit("Lección en curso: falta " + ", ".join(faltan))
            self._reload_grid()
            return
        try:
            self._bridge.add_load(p.groups, p.subject, p.teachers, p.hours, p.rooms or None)
            self._reset_pending()
        except ConfigError as exc:
            QMessageBox.warning(self, "No se pudo crear la lección", str(exc))

    # --- acciones -------------------------------------------------------- #
    def _selected_lessons(self) -> list[LessonRow]:
        rows = sorted({index.row() for index in self._table.selectionModel().selectedRows()})
        out: list[LessonRow] = []
        seen: set[str] = set()
        for r in rows:
            if 0 <= r < len(self._display):
                lesson = self._display[r].lesson
                if lesson.key not in seen:
                    seen.add(lesson.key)
                    out.append(lesson)
        return out

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

    # --- interacción en la tabla ----------------------------------------- #
    def _on_cell_clicked(self, row: int, column: int) -> None:
        """Clic en ⊞/⊟ (columna N.lec de un acople) expande o colapsa."""
        if column != 0 or not 0 <= row < len(self._display):
            return
        entry = self._display[row]
        if entry.kind != "parent":
            return
        cid = entry.lesson.coupling_id
        if cid in self._expanded:
            self._expanded.discard(cid)
        else:
            self._expanded.add(cid)
        self._reload_grid()

    def _on_cell_double(self, row: int, column: int) -> None:
        if row == len(self._display):  # fila vacía de alta
            self._blank_double(column)
            return
        if not 0 <= row < len(self._display):
            return
        lesson = self._display[row].lesson
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

    def _blank_double(self, column: int) -> None:
        """Doble-clic en la fila (*): elige docentes/grupos/aulas de la nueva lección."""
        tables = self._bridge.tables()
        if column == _TEACHERS_COL:
            dialog = _MultiPickDialog(
                tables.teachers,
                self,
                title="Docentes de la nueva lección",
                info="Marca uno o varios docentes.",
                preselect=tuple(self._pending.teachers),
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._pending.teachers = dialog.selected()
                self._try_create_pending()
        elif column == _GROUPS_COL:
            dialog = _MultiPickDialog(
                tables.groups,
                self,
                title="Grupos de la nueva lección",
                info="Marca uno o varios grupos.",
                preselect=tuple(self._pending.groups),
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._pending.groups = dialog.selected()
                self._try_create_pending()
        elif column == _ROOMS_COL:
            dialog = _MultiPickDialog(
                tables.rooms,
                self,
                title="Aulas de la nueva lección",
                info="Opcional: sin selección, el motor elige.",
                preselect=tuple(self._pending.rooms),
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._pending.rooms = dialog.selected()
                self._reload_grid()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        if row == len(self._display):  # fila vacía de alta
            if item.column() == _SUBJECT_COL:
                self._pending.subject = item.text().strip()
                self._try_create_pending()
            elif item.column() == _HHS_COL:
                with contextlib.suppress(ValueError):
                    self._pending.hours = max(1, int(item.text()))
                self._reload_grid()
            return
        if not 0 <= row < len(self._display):
            return
        lesson = self._display[row].lesson
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
