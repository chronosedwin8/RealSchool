"""Ventana Lecciones: la ventana de datos más importante (sección 8).

Una fila por línea de acople: la primera fila de cada lección lleva las columnas
de la lección (Per/sem, Dobles, Bloque...) y las siguientes solo las de su línea
(profesor, materia, clases, aula), como en Untis. Se eligió una tabla plana en
vez de un árbol porque los acoples se ven siempre (no hay que desplegar nada),
la navegación con teclado es la de una hoja de cálculo y ordenar/filtrar es
trivial; la lección se distingue por el número y el sombreado alterno.

Filtro por clase / profesor / materia / todas, que sigue la selección
sincronizada. Barra de suma abajo, con icono de estado: períodos frente a
capacidad de la rejilla (en rojo si la supera). Las sub-filas de un acople
llevan el icono de enlace; cada cabecera explica su columna al pasar el ratón.

**Carga masiva** (900 lecciones no se teclean una a una): Importar CSV,
Exportar CSV, Ctrl+C y Ctrl+V usan el formato plano de
`application.untis.bulk_lessons` -una fila por línea de acople, con el número
de lección como pegamento-, con la misma validación que la edición en celda y
todo en un solo paso de deshacer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import EditResult, MasterKind, UntisLessonRow
from scheduling_platform.application.untis.bulk import ImportReport, table_from_rows
from scheduling_platform.application.untis.bulk_lessons import (
    LESSON_FIELDS,
    LessonSource,
    export_lessons,
    import_lessons,
    lesson_rows,
    preview_lessons,
)

from ..icons import icon
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import ERROR_COLOR, fmt_int
from ..widgets.master_grid import (
    CSV_ENCODING,
    CSV_FILTER,
    ChoiceDelegate,
    entity_ids,
    is_checked,
    split_block,
)
from ..widgets.uikit import Banner, EmptyHint, icon_pixmap, make_action, set_texts, tool_button

type AnyIndex = QModelIndex | QPersistentModelIndex

#: Nivel de cada columna: `number` (solo lectura), `line` (línea del acople),
#: `lesson` (lección), `bool` (casilla de la lección) o `placed` (solo lectura).
COLUMNS: tuple[tuple[str, str], ...] = (
    ("number", "number"),
    ("classes", "line"),
    ("teacher", "line"),
    ("subject", "line"),
    ("room", "line"),
    ("periods_per_week", "lesson"),
    ("double_periods", "lesson"),
    ("block", "lesson"),
    ("time_grid", "lesson"),
    ("fixed", "bool"),
    ("ignore", "bool"),
    ("not_same_day", "bool"),
    ("weekly_value", "lesson"),
    ("placed", "placed"),
)
FIELDS: tuple[str, ...] = tuple(f for f, _ in COLUMNS)
LEVEL: dict[str, str] = dict(COLUMNS)

#: Modos de filtro: `(clave, tipo de selección, MasterKind de la lista)`.
MODES: tuple[tuple[str, str, MasterKind | None], ...] = (
    ("class", "class", MasterKind.CLASSES),
    ("teacher", "teacher", MasterKind.TEACHERS),
    ("subject", "subject", MasterKind.SUBJECTS),
    ("all", "", None),
)
MODE_KEYS: tuple[str, ...] = tuple(m for m, _, _ in MODES)

_SUB_ROW_COLOR = "#6b7280"
_UNPLACED_COLOR = "#fef3c7"


@dataclass(frozen=True, slots=True)
class LessonLine:
    """Una fila de la tabla: una línea de una lección."""

    lesson: UntisLessonRow
    line: int
    shade: bool
    """Sombreado alterno por lección (no por fila)."""

    @property
    def is_first(self) -> bool:
        return self.line == 0


def _lesson_text(row: UntisLessonRow, field: str) -> str:
    valores: dict[str, str] = {
        "number": str(row.number),
        "periods_per_week": str(row.periods_per_week),
        "double_periods": row.double_periods,
        "block": row.block,
        "time_grid": row.time_grid,
        "fixed": "x" if row.fixed else "",
        "ignore": "x" if row.ignore else "",
        "not_same_day": "x" if row.not_same_day else "",
        "weekly_value": f"{row.weekly_value:g}" if row.weekly_value else "",
        "placed": str(row.placed),
    }
    return valores.get(field, "")


def _line_text(row: UntisLessonRow, line: int, field: str) -> str:
    linea = row.lines[line]
    valores: dict[str, str] = {
        "classes": linea.classes,
        "teacher": linea.teacher,
        "subject": linea.subject,
        "room": linea.room,
    }
    return valores.get(field, "")


class LessonsModel(QAbstractTableModel):
    """Lecciones filtradas, aplanadas a una fila por línea."""

    edit_failed = Signal(str)

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.lessons: tuple[UntisLessonRow, ...] = ()
        self._rows: list[LessonLine] = []
        self._errors: dict[tuple[int, int, str], str] = {}
        """`(lección, línea, campo) -> motivo` (línea -1 = columna de la lección)."""

    def set_lessons(self, lessons: tuple[UntisLessonRow, ...]) -> None:
        self.beginResetModel()
        self.lessons = lessons
        self._rows = [
            LessonLine(le, i, n % 2 == 1)
            for n, le in enumerate(lessons)
            for i in range(max(1, len(le.lines)))
        ]
        numeros = {le.number for le in lessons}
        self._errors = {k: v for k, v in self._errors.items() if k[0] in numeros}
        self.endResetModel()

    def clear_errors(self) -> None:
        self._errors.clear()

    def line_at(self, row: int) -> LessonLine | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def row_of(self, number: int, line: int = 0) -> int:
        return next(
            (i for i, r in enumerate(self._rows) if r.lesson.number == number and r.line == line),
            -1,
        )

    def error_at(self, number: int, line: int, field: str) -> str:
        return self._errors.get((number, line, field), "")

    def text(self, row: int, field: str) -> str:
        fila = self._rows[row]
        nivel = LEVEL[field]
        if nivel == "line":
            return _line_text(fila.lesson, fila.line, field) if fila.lesson.lines else ""
        if not fila.is_first and field != "number":
            return ""
        return _lesson_text(fila.lesson, field)

    def _titles(self) -> tuple[str, ...]:
        return (
            self.tr("Nº"),
            self.tr("Cl"),
            self.tr("Prof"),
            self.tr("Mat"),
            self.tr("Aula"),
            self.tr("Per/sem"),
            self.tr("Dobles"),
            self.tr("Bloque"),
            self.tr("Rejilla"),
            self.tr("Fijar"),
            self.tr("Ignorar"),
            self.tr("No mismo día"),
            self.tr("Valor semanal"),
            self.tr("Colocadas"),
        )

    def _tooltips(self) -> tuple[str, ...]:
        return (
            self.tr("Nº: número de la lección; las sub-filas con enlace son líneas del acople"),
            self.tr("Cl: clases que reciben la lección, separadas por comas"),
            self.tr("Prof: profesor que da la lección; elígelo de la lista"),
            self.tr("Mat: materia de la lección; elígela de la lista"),
            self.tr("Aula: aula que pide la lección; elígela de la lista"),
            self.tr("Per/sem: cuántos períodos de esta lección hay a la semana"),
            self.tr("Dobles: cuántos dobles (dos períodos seguidos) quieres, mín-máx; escribe 1-2"),
            self.tr("Bloque: tamaño de los bloques de períodos seguidos, p. ej. 3"),
            self.tr("Rejilla: rejilla de tiempo en la que se coloca la lección"),
            self.tr("Fijar: la optimización no mueve los períodos ya colocados"),
            self.tr("Ignorar: la lección no se coloca ni cuenta en la optimización"),
            self.tr("No mismo día: como mucho un período de esta lección al día"),
            self.tr("Valor semanal: horas que cuenta para la carga del profesor"),
            self.tr("Colocadas: períodos ya colocados en el horario activo (amarillo si faltan)"),
        )

    # --- API de Qt ----------------------------------------------------------- #

    def rowCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008 - firma de Qt
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008 - firma de Qt
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(COLUMNS):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._titles()[section]
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltips()[section]
        return None

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        fila = self._rows[index.row()]
        campo, nivel = COLUMNS[index.column()]
        texto = self.text(index.row(), campo)
        linea = fila.line if nivel == "line" else -1
        error = self._errors.get((fila.lesson.number, linea, campo), "")
        if role == Qt.ItemDataRole.DisplayRole:
            return "" if nivel == "bool" else texto
        if role == Qt.ItemDataRole.EditRole:
            return texto
        if role == Qt.ItemDataRole.CheckStateRole and nivel == "bool" and fila.is_first:
            return Qt.CheckState.Checked if texto else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.BackgroundRole:
            if error:
                return QColor(ERROR_COLOR)
            if nivel == "placed" and fila.is_first and fila.lesson.unplaced:
                return QColor(_UNPLACED_COLOR)
            return QColor("#f3f4f6") if fila.shade else None
        if role == Qt.ItemDataRole.ForegroundRole and campo == "number" and not fila.is_first:
            return QColor(_SUB_ROW_COLOR)
        if role == Qt.ItemDataRole.DecorationRole and campo == "number" and not fila.is_first:
            return icon("couple")
        if role == Qt.ItemDataRole.ToolTipRole:
            if error:
                return error
            if campo == "number" and fila.lesson.is_coupled:
                return self.tr("Lección {0} acoplada: línea {1} de {2}").format(
                    fila.lesson.number, fila.line + 1, len(fila.lesson.lines)
                )
            if campo == "placed" and fila.is_first and fila.lesson.unplaced:
                return self.tr("Faltan {0} período(s) por colocar").format(fila.lesson.unplaced)
        return None

    def flags(self, index: AnyIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        fila = self._rows[index.row()]
        nivel = COLUMNS[index.column()][1]
        if nivel == "line" and fila.lesson.lines:
            return base | Qt.ItemFlag.ItemIsEditable
        if nivel == "lesson" and fila.is_first:
            return base | Qt.ItemFlag.ItemIsEditable
        if nivel == "bool" and fila.is_first:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def setData(self, index: AnyIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or not self.bridge.has_session:
            return False
        campo, nivel = COLUMNS[index.column()]
        if role == Qt.ItemDataRole.CheckStateRole and nivel == "bool":
            texto = "x" if is_checked(value) else ""
        elif role == Qt.ItemDataRole.EditRole and nivel in ("line", "lesson"):
            texto = "" if value is None else str(value)
        else:
            return False
        return self.edit(index.row(), campo, texto).ok

    def edit(self, row: int, field: str, text: str) -> EditResult:
        """Edita una celda (de la línea o de la lección) a través del puente."""
        fila = self.line_at(row)
        nivel = LEVEL.get(field)
        if fila is None or nivel not in ("line", "lesson", "bool"):
            return EditResult.failure(self.tr("Columna no editable"))
        if text == self.text(row, field):
            return EditResult.success()
        svc, numero = self.bridge.service, fila.lesson.number
        if nivel == "line":
            linea = fila.line
            clave = (numero, linea, field)
            resultado = self.bridge.edit(
                lambda: svc.set_line_field(self.bridge.session, numero, linea, field, text)
            )
        else:
            clave = (numero, -1, field)
            resultado = self.bridge.edit(
                lambda: svc.set_lesson_field(self.bridge.session, numero, field, text)
            )
        if resultado.ok:
            self._errors.pop(clave, None)
        else:
            self._errors[clave] = self.tr("Valor rechazado «{0}»: {1}").format(
                text, resultado.message
            )
            self.edit_failed.emit(resultado.message)
        col = FIELDS.index(field)
        self.dataChanged.emit(self.index(row, col), self.index(row, col))
        return resultado


class NewLessonDialog(QDialog):
    """Datos de una lección nueva: materia, profesor, clases y períodos."""

    def __init__(self, bridge: FacadeBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Nueva lección"))
        self.subject = QComboBox()
        self.subject.addItems(list(entity_ids(bridge, MasterKind.SUBJECTS)))
        self.teacher = QComboBox()
        self.teacher.addItems(["", *entity_ids(bridge, MasterKind.TEACHERS)])
        self.classes = QListWidget()
        for clase in entity_ids(bridge, MasterKind.CLASSES):
            item = QListWidgetItem(clase)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.classes.addItem(item)
        self.periods = QSpinBox()
        self.periods.setRange(1, 40)
        self.periods.setValue(1)
        if bridge.selection is not None and bridge.selection[0] == "class":
            self.check_classes((bridge.selection[1],))
        formulario = QFormLayout()
        formulario.addRow(self.tr("Materia"), self.subject)
        formulario.addRow(self.tr("Profesor"), self.teacher)
        formulario.addRow(self.tr("Clases"), self.classes)
        formulario.addRow(self.tr("Períodos por semana"), self.periods)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.button(QDialogButtonBox.StandardButton.Ok).setIcon(icon("lesson_add"))
        botones.button(QDialogButtonBox.StandardButton.Cancel).setIcon(icon("unplace"))
        self.subject.setToolTip(self.tr("Materia que se enseña en la lección"))
        self.teacher.setToolTip(self.tr("Profesor que la da (se puede dejar vacío)"))
        self.classes.setToolTip(self.tr("Marca las clases que reciben la lección"))
        self.periods.setToolTip(self.tr("Cuántos períodos a la semana"))
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        raiz = QVBoxLayout(self)
        raiz.addLayout(formulario)
        raiz.addWidget(botones)

    def check_classes(self, classes: tuple[str, ...]) -> None:
        for i in range(self.classes.count()):
            item = self.classes.item(i)
            marcado = item.text() in classes
            item.setCheckState(Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked)

    def values(self) -> tuple[str, str | None, tuple[str, ...], int]:
        """`(materia, profesor o None, clases, períodos)`."""
        clases = tuple(
            self.classes.item(i).text()
            for i in range(self.classes.count())
            if self.classes.item(i).checkState() == Qt.CheckState.Checked
        )
        return (
            self.subject.currentText(),
            self.teacher.currentText() or None,
            clases,
            self.periods.value(),
        )


class LessonsWindow(QWidget):
    """Lecciones por clase, profesor, materia o todas, con barra de suma."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self._loading = False
        self._sized = False

        self.mode_combo = QComboBox()
        iconos = {"class": "classes", "teacher": "teachers", "subject": "subjects", "all": "table"}
        for clave in MODE_KEYS:
            self.mode_combo.addItem(icon(iconos[clave]), clave, clave)
        self.mode_combo.currentIndexChanged.connect(self._on_mode)
        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(140)
        self.entity_combo.currentIndexChanged.connect(self._on_entity)

        self.new_button = tool_button("lesson_add", self.new_lesson)
        self.couple_button = tool_button("couple", self.couple)
        self.uncouple_button = tool_button("uncouple", self.uncouple)
        self.remove_button = tool_button("delete", self.remove)
        self.copy_button = tool_button("copy", self.copy_selection)
        self.paste_button = tool_button("table", self.paste_clipboard)
        self.import_button = tool_button("import", self.ask_import)
        self.export_button = tool_button("export", self.ask_export)

        self.model = LessonsModel(bridge)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(ChoiceDelegate(self._choices, self.view))
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(22)
        self.view.horizontalHeader().setSectionsMovable(True)
        self.view.selectionModel().currentRowChanged.connect(self._on_current_row)
        self.view.doubleClicked.connect(self._on_double_click)
        self.copy_action = make_action(self, "copy", self.copy_selection)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.paste_action = make_action(self, "table", self.paste_clipboard)
        self.paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        for accion in (self.copy_action, self.paste_action):
            accion.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.view.addAction(accion)
        self.hint = EmptyHint(self.view)

        self.sum_icon = QLabel()
        self.sum_bar = QLabel()
        self.sum_bar.setMargin(4)
        self.sum_frame = QFrame()
        self.sum_frame.setFrameShape(QFrame.Shape.StyledPanel)
        suma = QHBoxLayout(self.sum_frame)
        suma.setContentsMargins(6, 0, 6, 0)
        suma.addWidget(self.sum_icon)
        suma.addWidget(self.sum_bar, 1)
        self.message = Banner("error")
        self.message.hide()

        barra = QHBoxLayout()
        barra.setSpacing(4)
        for boton in (
            self.new_button,
            self.couple_button,
            self.uncouple_button,
            self.remove_button,
            self.copy_button,
            self.paste_button,
            self.import_button,
            self.export_button,
        ):
            barra.addWidget(boton)
        barra.addSpacing(16)
        self.filter_label = QLabel()
        barra.addWidget(self.filter_label)
        barra.addWidget(self.mode_combo)
        barra.addWidget(self.entity_combo)
        barra.addStretch(1)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)
        raiz.addLayout(barra)
        raiz.addWidget(self.view, 1)
        raiz.addWidget(self.message)
        raiz.addWidget(self.sum_frame)

        self.model.edit_failed.connect(self.show_message)
        bridge.refreshed.connect(self.refresh)
        bridge.project_opened.connect(self.model.clear_errors)
        bridge.selection_changed.connect(self.follow_selection)
        bridge.lesson_selected.connect(self.select_lesson)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()
        if bridge.selection is not None:
            self.follow_selection(*bridge.selection)
        self.refresh()

    # --- filtro --------------------------------------------------------------- #

    @property
    def mode(self) -> str:
        return str(self.mode_combo.currentData() or "all")

    @property
    def entity(self) -> str:
        return self.entity_combo.currentText() if self.mode != "all" else ""

    def set_filter(self, mode: str, entity_id: str = "") -> None:
        """Cambia el filtro (`class`, `teacher`, `subject` o `all`)."""
        self._loading = True
        try:
            self.mode_combo.setCurrentIndex(MODE_KEYS.index(mode))
            self._fill_entities()
            if entity_id:
                self.entity_combo.setCurrentIndex(max(0, self.entity_combo.findText(entity_id)))
        finally:
            self._loading = False
        self.refresh()

    def follow_selection(self, kind: str, entity_id: str) -> None:
        if kind in ("class", "teacher", "subject") and (kind, entity_id) != (
            self.mode,
            self.entity,
        ):
            self.set_filter(kind, entity_id)

    def _fill_entities(self) -> None:
        actual = self.entity_combo.currentText()
        tipo = {m: k for m, _, k in MODES}.get(self.mode)
        ids = entity_ids(self.bridge, tipo) if tipo is not None else ()
        self.entity_combo.clear()
        self.entity_combo.addItems(list(ids))
        self.entity_combo.setEnabled(tipo is not None)
        if actual in ids:
            self.entity_combo.setCurrentIndex(ids.index(actual))

    def _on_mode(self, _index: int) -> None:
        if self._loading:
            return
        self._loading = True
        try:
            self._fill_entities()
        finally:
            self._loading = False
        self.refresh()
        self._announce()

    def _on_entity(self, _index: int) -> None:
        if self._loading:
            return
        self.refresh()
        self._announce()

    def _announce(self) -> None:
        if self.mode != "all" and self.entity:
            self.bridge.select(self.mode, self.entity)

    # --- carga ------------------------------------------------------------------ #

    def refresh(self) -> None:
        actual = self.current_lesson()
        self._loading = True
        try:
            self._fill_entities()
        finally:
            self._loading = False
        if not self.bridge.has_session:
            self.model.set_lessons(())
        else:
            svc, s = self.bridge.service, self.bridge.session
            entidad = self.entity or None
            if self.mode == "class":
                filas = svc.lessons(s, class_id=entidad) if entidad else ()
            elif self.mode == "teacher":
                filas = svc.lessons(s, teacher_id=entidad) if entidad else ()
            elif self.mode == "subject":
                filas = svc.lessons(s, subject_id=entidad) if entidad else ()
            else:
                filas = svc.lessons(s)
            self.model.set_lessons(filas)
        if actual is not None:
            self._select_row(self.model.row_of(*actual))
        if self.model.lessons and not self._sized:
            # Primera carga con datos: anchos según el contenido (una sola vez).
            self._sized = True
            self.view.resizeColumnsToContents()
            cabecera = self.view.horizontalHeader()
            for col, (_campo, nivel) in enumerate(COLUMNS):
                minimo = 110 if nivel == "line" else 70
                cabecera.resizeSection(col, max(cabecera.sectionSize(col), minimo))
        self._update_sum_bar()
        self._update_hint()
        self._update_buttons()

    def hint_text(self) -> str:
        """Ayuda que se ve sobre la tabla vacía ("" si hay lecciones)."""
        if not self.bridge.has_session:
            return self.tr("Abre o crea un proyecto para ver sus lecciones.")
        if self.model.lessons:
            return ""
        if self.mode != "all" and not self.entity:
            return self.tr("Elige arriba una clase, profesor o materia, o pasa a «Todas».")
        if self.mode == "all":
            return self.tr(
                "Aún no hay lecciones. Pulsa «Nueva lección» para decir qué materia da "
                "cada profesor a cada clase y cuántas horas a la semana."
            )
        return self.tr(
            "No hay lecciones de {0}. Pulsa «Nueva lección» para crear la primera."
        ).format(self.entity)

    def _update_hint(self) -> None:
        self.hint.show_hint(self.hint_text())

    def _update_buttons(self) -> None:
        abierto = self.bridge.has_session
        hay = self.current_lesson() is not None
        self.new_button.setEnabled(abierto)
        for boton in (self.couple_button, self.uncouple_button, self.remove_button):
            boton.setEnabled(abierto and hay)
        for widget in (self.paste_button, self.paste_action, self.import_button):
            widget.setEnabled(abierto)
        for widget in (self.copy_button, self.copy_action, self.export_button):
            widget.setEnabled(abierto and bool(self.model.lessons))

    def _set_sum_state(self, kind: str) -> None:
        self.sum_icon.setPixmap(icon_pixmap(kind, "button"))
        self.sum_icon.setProperty("state", kind)

    def _update_sum_bar(self) -> None:
        self.sum_bar.setStyleSheet("")
        if not self.bridge.has_session:
            self.sum_bar.setText("")
            self.sum_icon.clear()
            return
        if self.mode in ("class", "teacher") and self.entity:
            r = self.bridge.service.load_summary(self.bridge.session, self.mode, self.entity)
            self.sum_bar.setText(
                self.tr("{0}: períodos {1} / capacidad {2} · colocados {3}").format(
                    self.entity, fmt_int(r.periods), fmt_int(r.capacity), fmt_int(r.placed)
                )
            )
            if r.overloaded:
                self.sum_bar.setStyleSheet(f"background: {ERROR_COLOR}; font-weight: bold;")
                self.sum_bar.setToolTip(
                    self.tr("Hay más períodos que huecos en su rejilla: no caben todos")
                )
                self._set_sum_state("error")
            elif r.placed < r.periods:
                self.sum_bar.setToolTip(self.tr("Quedan períodos sin colocar en el horario"))
                self._set_sum_state("warning")
            else:
                self.sum_bar.setToolTip(self.tr("Todo cabe y todo está colocado"))
                self._set_sum_state("ok")
            self.sum_bar.setProperty("overloaded", r.overloaded)
            return
        lecciones = self.model.lessons
        periodos = sum(le.periods_per_week for le in lecciones if not le.ignore)
        colocados = sum(min(le.placed, le.periods_per_week) for le in lecciones if not le.ignore)
        self.sum_bar.setText(
            self.tr("{0} lecciones: períodos {1} · colocados {2}").format(
                fmt_int(len(lecciones)), fmt_int(periodos), fmt_int(colocados)
            )
        )
        self.sum_bar.setToolTip(self.tr("Suma de períodos semanales y de los ya colocados"))
        self._set_sum_state("ok" if colocados >= periodos else "warning")
        self.sum_bar.setProperty("overloaded", False)

    # --- selección de lección ------------------------------------------------- #

    def current_lesson(self) -> tuple[int, int] | None:
        """`(lección, línea)` de la fila actual."""
        fila = self.model.line_at(self.view.currentIndex().row())
        return (fila.lesson.number, fila.line) if fila is not None else None

    def _select_row(self, row: int) -> None:
        """Mueve la fila actual sin volver a anunciar la lección (evita ecos)."""
        if row < 0:
            return
        indice = self.model.index(row, 0)
        previo = self._loading
        self._loading = True
        try:
            self.view.setCurrentIndex(indice)
        finally:
            self._loading = previo
        self.view.scrollTo(indice)

    def select_lesson(self, number: int) -> None:
        """Enfoca una lección (desde Diagnóstico, horarios...); si está filtrada, muestra todas."""
        actual = self.current_lesson()
        if actual is not None and actual[0] == number:
            return
        fila = self.model.row_of(number)
        if fila < 0:
            if not self.bridge.has_session or not any(
                le.number == number for le in self.bridge.service.lessons(self.bridge.session)
            ):
                return
            self.set_filter("all")
            fila = self.model.row_of(number)
        self._select_row(fila)

    def _on_current_row(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self._update_buttons()
        fila = self.model.line_at(current.row())
        if fila is not None and not self._loading:
            self.bridge.select_lesson(fila.lesson.number)

    def _on_double_click(self, index: QModelIndex) -> None:
        fila = self.model.line_at(index.row())
        if fila is not None:
            self.bridge.select_lesson(fila.lesson.number)

    # --- órdenes -------------------------------------------------------------- #

    def _choices(self, index: AnyIndex) -> tuple[str, ...] | None:
        campo = COLUMNS[index.column()][0]
        tipos = {
            "teacher": MasterKind.TEACHERS,
            "subject": MasterKind.SUBJECTS,
            "room": MasterKind.ROOMS,
        }
        if campo in tipos:
            return entity_ids(self.bridge, tipos[campo])
        if campo == "time_grid" and self.bridge.has_session:
            return tuple(g.id for g in self.bridge.service.grids(self.bridge.session))
        return None

    def new_lesson(self) -> None:
        dialogo = NewLessonDialog(self.bridge, self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            self.create_lesson(*dialogo.values())

    def create_lesson(
        self, subject: str, teacher: str | None, classes: tuple[str, ...], periods: int
    ) -> EditResult:
        """Añade la lección y la selecciona; devuelve su número en `message`."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        svc = self.bridge.service
        resultado = self.bridge.edit(
            lambda: svc.add_lesson(
                self.bridge.session,
                subject=subject,
                teacher=teacher,
                classes=classes,
                periods=periods,
            )
        )
        if not resultado.ok:
            self.show_message(resultado.message)
            return resultado
        self.refresh()
        self.select_lesson(int(resultado.message))
        return resultado

    def _run(self, build: Callable[[int, int], EditResult]) -> EditResult:
        actual = self.current_lesson()
        if actual is None or not self.bridge.has_session:
            resultado = EditResult.failure(self.tr("Selecciona una lección"))
        else:
            resultado = self.bridge.edit(lambda: build(*actual))
        if not resultado.ok:
            self.show_message(resultado.message)
        else:
            self.message.hide()
        return resultado

    def couple(self) -> EditResult:
        """Acopla una línea nueva a la lección actual."""
        svc = self.bridge.service
        return self._run(lambda number, _line: svc.add_line(self.bridge.session, number))

    def uncouple(self) -> EditResult:
        """Quita la línea actual del acople."""
        svc = self.bridge.service
        return self._run(lambda number, line: svc.remove_line(self.bridge.session, number, line))

    def remove(self) -> EditResult:
        """Borra la lección actual."""
        svc = self.bridge.service
        return self._run(lambda number, _line: svc.remove_lesson(self.bridge.session, number))

    def show_message(self, text: str) -> None:
        self.message.show_message(text, "error")
        if text:
            self.bridge.status.emit(text)

    # --- carga masiva: copiar, pegar, importar y exportar ----------------------- #

    def copy_selection(self) -> str:
        """Copia la lección actual (o todas las que se ven) en el formato de importación."""
        if not self.bridge.has_session:
            return ""
        actual = self.current_lesson()
        numeros = [actual[0]] if actual is not None else [le.number for le in self.model.lessons]
        filas = lesson_rows(self.bridge.session, numeros)
        texto = "\n".join("\t".join(f) for f in filas)
        if texto:
            QGuiApplication.clipboard().setText(texto)
            self._report(
                self.tr("{0} línea(s) copiada(s) al portapapeles.").format(len(filas)), True, 1
            )
        return texto

    def paste_clipboard(self) -> bool:
        return self.paste_text(QGuiApplication.clipboard().text())

    def paste_text(self, text: str) -> bool:
        """Pega líneas en el formato de importación: crea y actualiza lecciones."""
        bloque = split_block(text)
        if not bloque or not self.bridge.has_session:
            self.show_message(self.tr("El portapapeles no trae ninguna línea de lección."))
            return False
        recortado = [fila[: len(LESSON_FIELDS)] for fila in bloque]
        ancho = max(len(f) for f in recortado)
        return self._run_import(table_from_rows(LESSON_FIELDS[:ancho], recortado))

    def _run_import(self, source: LessonSource) -> bool:
        """Importa y avisa de lo que entró y lo que no; en un solo paso de deshacer."""
        informe: list[ImportReport] = []

        def aplicar() -> EditResult:
            resultado = import_lessons(self.bridge.session, source)
            informe.append(resultado)
            return EditResult(resultado.ok, resultado.summary().splitlines()[0])

        self.bridge.edit(aplicar)
        if not informe:
            self.show_message(self.tr("Espera a que termine la optimización"))
            return False
        self.refresh()
        self._report(informe[0].summary(), informe[0].ok, informe[0].rows_ok)
        return informe[0].ok

    def _report(self, text: str, ok: bool, entered: int) -> None:
        """Franja de aviso: correcto, aviso (entró parte) o error (no entró nada)."""
        self.message.show_message(text, "ok" if ok else ("warning" if entered else "error"))
        self.bridge.status.emit(text.splitlines()[0])

    def ask_import(self) -> None:
        """Pide el CSV, enseña qué va a pasar y, si se confirma, lo importa."""
        if not self.bridge.has_session:
            return
        ruta, _ = QFileDialog.getOpenFileName(
            self, self.tr("Importar lecciones CSV"), "", CSV_FILTER
        )
        if not ruta:
            return
        previo = preview_lessons(self.bridge.session, Path(ruta))
        falta = previo.missing_summary()
        aviso = (
            self.tr("{0}\nDa de alta eso primero y vuelve a importar.\n\n").format(falta)
            if falta
            else ""
        )
        respuesta = QMessageBox.question(
            self,
            self.tr("Importar lecciones CSV"),
            self.tr("Se va a importar «{0}»:\n\n{1}{2}\n\n¿Continúo?").format(
                Path(ruta).name, aviso, previo.summary()
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if respuesta == QMessageBox.StandardButton.Yes:
            self.import_csv(ruta)

    def import_csv(self, path: str | Path) -> ImportReport | None:
        """Importa las lecciones del CSV en un solo paso de deshacer."""
        if not self.bridge.has_session:
            return None
        informe: list[ImportReport] = []

        def aplicar() -> EditResult:
            resultado = import_lessons(self.bridge.session, Path(path))
            informe.append(resultado)
            return EditResult(resultado.ok, resultado.summary().splitlines()[0])

        self.bridge.edit(aplicar)
        if not informe:
            self.show_message(self.tr("Espera a que termine la optimización"))
            return None
        self.refresh()
        self._report(informe[0].summary(), informe[0].ok, informe[0].rows_ok)
        return informe[0]

    def ask_export(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(
            self, self.tr("Exportar lecciones CSV"), "lecciones.csv", CSV_FILTER
        )
        if ruta:
            self.export_csv(ruta)

    def export_csv(self, path: str | Path) -> Path | None:
        """Escribe todas las lecciones como CSV, listas para editarlas en Excel."""
        if not self.bridge.has_session:
            return None
        destino = Path(path)
        if not destino.suffix:
            destino = destino.with_suffix(".csv")
        texto = export_lessons(self.bridge.session, language=self.bridge.language)
        try:
            destino.write_text(texto, encoding=CSV_ENCODING, newline="")
        except OSError as exc:
            self.show_message(self.tr("No se pudo escribir {0}: {1}").format(destino.name, exc))
            return None
        cuantas = len(self.bridge.service.lessons(self.bridge.session))
        self._report(
            self.tr("{0} lección(es) exportadas a {1}.").format(cuantas, destino.name), True, 1
        )
        return destino

    # --- idioma ------------------------------------------------------------------- #

    def _retranslate(self) -> None:
        nombres = {
            "class": self.tr("Por clase"),
            "teacher": self.tr("Por profesor"),
            "subject": self.tr("Por materia"),
            "all": self.tr("Todas"),
        }
        for i, clave in enumerate(MODE_KEYS):
            self.mode_combo.setItemText(i, nombres[clave])
        self.filter_label.setText(self.tr("Mostrar:"))
        self.mode_combo.setToolTip(
            self.tr("Qué lecciones se ven: de una clase, profesor, materia o todas")
        )
        self.entity_combo.setToolTip(self.tr("La clase, profesor o materia cuyas lecciones se ven"))
        set_texts(
            self.new_button,
            self.tr("Nueva lección"),
            self.tr("Crea una lección: materia, profesor, clases y períodos por semana"),
        )
        set_texts(
            self.couple_button,
            self.tr("Acoplar"),
            self.tr(
                "Añade una línea al acople de la lección: otro profesor o grupo a la misma hora"
            ),
        )
        set_texts(
            self.uncouple_button,
            self.tr("Desacoplar"),
            self.tr("Quita la línea seleccionada del acople"),
        )
        set_texts(
            self.remove_button,
            self.tr("Borrar"),
            self.tr("Borra la lección seleccionada y sus períodos colocados (se puede deshacer)"),
        )
        copiar = self.tr(
            "Copia la lección seleccionada (o todas las que se ven) para pegarla en Excel (Ctrl+C)"
        )
        pegar = self.tr(
            "Pega líneas de lección desde Excel: una fila por línea, el número acopla; "
            "en un solo deshacer (Ctrl+V)"
        )
        importar = self.tr(
            "Carga de golpe un CSV de lecciones, una fila por línea; antes dice qué va a pasar"
        )
        exportar = self.tr(
            "Guarda todas las lecciones como CSV para editarlas en Excel y volver a importarlas"
        )
        for objetivo, texto, ayuda in (
            (self.copy_button, self.tr("Copiar"), copiar),
            (self.copy_action, self.tr("Copiar"), copiar),
            (self.paste_button, self.tr("Pegar"), pegar),
            (self.paste_action, self.tr("Pegar"), pegar),
            (self.import_button, self.tr("Importar CSV"), importar),
            (self.export_button, self.tr("Exportar CSV"), exportar),
        ):
            set_texts(objetivo, texto, ayuda)
        self._update_hint()
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)
        self._update_sum_bar()


register(
    WindowSpec(
        key="lessons",
        title="Lecciones",
        title_de="Unterricht",
        tab=RibbonTab.LESSONS,
        factory=LessonsWindow,
        order=1,
        icon="lessons",
        tooltip="Qué materia da cada profesor a cada clase y cuántas horas a la semana.",
        tooltip_de=(
            "Welches Fach jede Lehrkraft in jeder Klasse unterrichtet und wie viele Stunden pro "
            "Woche."
        ),
    )
)
