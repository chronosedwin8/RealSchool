"""`MasterDataGrid`: la cuadrícula única de las ventanas de datos maestros.

Un solo widget para Clases, Profesores, Aulas, Materias, Departamentos y Grupos
de alumnos (riesgo "complejidad MDI" del documento maestro). Todo sale de la
`MasterTable` de la Fachada: las columnas (`ColumnSpec`), las filas, los
desplegables de referencias y los hallazgos del diagnóstico de datos.

- Modelo propio (`QAbstractTableModel`) + `QTableView`: con cientos de filas la
  vista solo pide las celdas visibles.
- Columnas configurables: menú contextual de la cabecera para mostrar/ocultar,
  arrastrar para reordenar, redimensionar. La disposición se guarda en
  `QSettings` por ventana y se restaura al construir (y tras cada recarga).
- Edición en celda con validación inmediata: si la Fachada rechaza el valor la
  celda se pinta en rojo con el motivo como ayuda emergente, como en Untis.
- Última fila en blanco (con un texto gris que lo explica): escribir un nombre
  corto añade la entidad. El botón Añadir de la barra lleva a esa fila.
- Barra de herramientas con iconos (Añadir, Borrar, Deseos, Columnas) y filtro
  con lupa; ayuda emergente en cada cabecera con el significado de la columna.
- Estado vacío: con la tabla sin filas se ve un texto que dice qué hacer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QSettings,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import (
    ColumnSpec,
    EditResult,
    MasterKind,
    MasterRow,
    MasterTable,
    ValueType,
)

from ..icons import icon
from ..qt_bridge import FacadeBridge
from ..theme import ERROR_COLOR
from .uikit import Banner, EmptyHint, make_action, set_texts, tool_button

type AnyIndex = QModelIndex | QPersistentModelIndex

#: Tipo de selección sincronizada de cada ventana (las demás no filtran nada).
SELECTION_KIND: dict[MasterKind, str] = {
    MasterKind.CLASSES: "class",
    MasterKind.TEACHERS: "teacher",
    MasterKind.ROOMS: "room",
    MasterKind.SUBJECTS: "subject",
}

#: Ventana de datos maestros de cada tipo de selección (inverso del anterior).
KIND_OF_SELECTION: dict[str, MasterKind] = {v: k for k, v in SELECTION_KIND.items()}

#: Clave de la ventana Deseos de tiempo en el registro.
REQUESTS_KEY = "requests"


def layout_settings() -> QSettings:
    """Almacén de la disposición de columnas (las pruebas lo sustituyen)."""
    return QSettings("RealSchool", "RealSchool")


def entity_ids(bridge: FacadeBridge, kind: MasterKind) -> tuple[str, ...]:
    """Nombres cortos de las entidades de un tipo (para desplegables)."""
    if not bridge.has_session:
        return ()
    return tuple(r.key for r in bridge.service.master_table(bridge.session, kind).rows)


def is_checked(value: object) -> bool:
    """Valor de `CheckStateRole` (según la versión llega como enum o como entero)."""
    return value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)


def warning_icon() -> QIcon:
    return icon("warning")


# --------------------------------------------------------------------------- #
# Delegado con desplegable (referencias)
# --------------------------------------------------------------------------- #


class ChoiceDelegate(QStyledItemDelegate):
    """Edita con un desplegable las columnas que tienen lista de valores.

    `choices(index)` devuelve los valores posibles o `None` para usar el editor
    de texto normal. La opción vacía siempre va primero (quitar la referencia).
    """

    def __init__(
        self, choices: Callable[[AnyIndex], tuple[str, ...] | None], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._choices = choices

    def createEditor(
        self, parent: QWidget, option: QStyleOptionViewItem, index: AnyIndex
    ) -> QWidget:
        valores = self._choices(index)
        if valores is None:
            return super().createEditor(parent, option, index)
        combo = QComboBox(parent)
        combo.addItems(["", *valores])
        return combo

    def setEditorData(self, editor: QWidget, index: AnyIndex) -> None:
        if isinstance(editor, QComboBox):
            texto = str(index.data(Qt.ItemDataRole.EditRole) or "")
            posicion = editor.findText(texto)
            editor.setCurrentIndex(max(0, posicion))
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor: QWidget, model: Any, index: AnyIndex) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
            return
        super().setModelData(editor, model, index)


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #


class MasterTableModel(QAbstractTableModel):
    """Filas de una `MasterTable` más una fila en blanco para añadir."""

    edit_failed = Signal(str)
    """Mensaje de una edición rechazada por la Fachada."""

    def __init__(self, bridge: FacadeBridge, kind: MasterKind) -> None:
        super().__init__()
        self.bridge = bridge
        self.kind = kind
        self.table: MasterTable | None = None
        self._rows: list[MasterRow] = []
        self._errors: dict[tuple[str, str], str] = {}
        """`(clave, campo) -> motivo` de las celdas rechazadas (en rojo)."""
        self._new_error = ""
        self._icon: QIcon | None = None

    # --- carga -------------------------------------------------------------- #

    def reload(self) -> None:
        self.beginResetModel()
        if self.bridge.has_session:
            self.table = self.bridge.service.master_table(self.bridge.session, self.kind)
            self._rows = list(self.table.rows)
        else:
            self.table = None
            self._rows = []
        claves = {r.key for r in self._rows}
        self._errors = {k: v for k, v in self._errors.items() if k[0] in claves}
        self.endResetModel()

    def clear_errors(self) -> None:
        self._errors.clear()
        self._new_error = ""

    @property
    def columns(self) -> tuple[ColumnSpec, ...]:
        return self.table.columns if self.table is not None else ()

    @property
    def rows(self) -> tuple[MasterRow, ...]:
        return tuple(self._rows)

    def is_blank_row(self, row: int) -> bool:
        return self.table is not None and row == len(self._rows)

    def row_at(self, row: int) -> MasterRow | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def key_at(self, row: int) -> str | None:
        return self._rows[row].key if 0 <= row < len(self._rows) else None

    def row_of(self, key: str) -> int:
        return next((i for i, r in enumerate(self._rows) if r.key == key), -1)

    def error_at(self, key: str, field: str) -> str:
        return self._errors.get((key, field), "")

    def references(self, column: int) -> tuple[str, ...] | None:
        if self.table is None or not 0 <= column < len(self.columns):
            return None
        spec = self.columns[column]
        if spec.reference is None:
            return None
        return self.table.references.get(spec.field, ())

    def field_help(self, field: str) -> str:
        """Qué significa una columna y cómo se escribe (ayuda de la cabecera)."""
        ayudas = {
            "id": self.tr("identifica la fila en todas las ventanas; no se puede cambiar"),
            "name": self.tr("el nombre largo que aparece en horarios e informes"),
            "surname": self.tr("apellido del profesor"),
            "forename": self.tr("nombre de pila del profesor"),
            "email": self.tr("dirección de correo (para enviar el horario)"),
            "text": self.tr("nota libre, no afecta al horario"),
            "time_grid": self.tr("qué rejilla de tiempo (días y horas) usa; elígela de la lista"),
            "home_room": self.tr("aula donde da clase normalmente; elígela de la lista"),
            "department": self.tr("departamento al que pertenece; elígelo de la lista"),
            "students": self.tr("número de alumnos (se compara con la capacidad del aula)"),
            "level": self.tr("curso o nivel, p. ej. 7"),
            "periods_per_day": self.tr(
                "cuántas horas de clase puede tener al día; escribe mínimo-máximo, p. ej. 4-7"
            ),
            "lunch_break": self.tr(
                "períodos libres para comer en la franja de mediodía; escribe p. ej. 1-2"
            ),
            "main_subjects_per_day": self.tr("máximo de períodos de materias principales al día"),
            "main_subjects_consecutive": self.tr(
                "máximo de materias principales seguidas sin otra en medio"
            ),
            "days_per_week_max": self.tr("días de la semana que puede venir como máximo"),
            "ntp_per_day": self.tr(
                "horas libres entre clases (huecos) al día; escribe mínimo-máximo, p. ej. 0-2"
            ),
            "ntp_per_week": self.tr("huecos a la semana; escribe mínimo-máximo, p. ej. 0-6"),
            "consecutive_max": self.tr("períodos seguidos como máximo sin descanso"),
            "status": self.tr("situación administrativa (texto libre)"),
            "payroll_number": self.tr("número de personal o de nómina"),
            "gender": self.tr("género (texto libre)"),
            "capacity": self.tr("plazas del aula"),
            "alternative_room": self.tr("aula que se usa si esta está ocupada"),
            "room_weight": self.tr("0-4: cuánto importa dar clase en esta aula (4 = mucho)"),
            "main_subject": self.tr("marcado: es materia principal (se reparte por las mañanas)"),
            "not_same_day": self.tr("marcado: no dar esta materia dos veces el mismo día"),
            "double_period_required": self.tr("marcado: la materia se da siempre en dobles"),
            "required_room": self.tr("aula en la que se tiene que dar esta materia"),
            "subject_group": self.tr("grupo de materias que no deben ir seguidas"),
            "fore_color": self.tr("color del texto en los horarios, #RRGGBB"),
            "back_color": self.tr("color de fondo en los horarios, #RRGGBB"),
            "subject": self.tr("materia del grupo de alumnos; elígela de la lista"),
            "classes": self.tr("clases separadas por comas"),
        }
        return ayudas.get(field, "")

    # --- API de Qt ----------------------------------------------------------- #

    def rowCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008 - firma de Qt
        if parent.isValid() or self.table is None:
            return 0
        return len(self._rows) + 1

    def columnCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008 - firma de Qt
        return 0 if parent.isValid() else len(self.columns)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.columns):
            spec = self.columns[section]
            if role == Qt.ItemDataRole.DisplayRole:
                return spec.title(self.bridge.language)
            if role == Qt.ItemDataRole.ToolTipRole:
                ayuda = self.field_help(spec.field)
                titulo = spec.title(self.bridge.language)
                return f"{titulo}: {ayuda}" if ayuda else titulo
            return None
        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            return "*" if self.is_blank_row(section) else str(section + 1)
        return None

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or self.table is None:
            return None
        fila, col = index.row(), index.column()
        spec = self.columns[col]
        if self.is_blank_row(fila):
            return self._blank_data(col, role)
        row = self._rows[fila]
        texto = row.cells[col] if col < len(row.cells) else ""
        error = self._errors.get((row.key, spec.field), "")
        if role == Qt.ItemDataRole.DisplayRole:
            return "" if spec.value_type is ValueType.BOOL else texto
        if role == Qt.ItemDataRole.EditRole:
            return texto
        if role == Qt.ItemDataRole.CheckStateRole and spec.value_type is ValueType.BOOL:
            return Qt.CheckState.Checked if texto else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.BackgroundRole and error:
            return QColor(ERROR_COLOR)
        if role == Qt.ItemDataRole.ToolTipRole:
            if error:
                return error
            if col == 0 and row.issues:
                return "\n".join(row.issues)
            return None
        if role == Qt.ItemDataRole.DecorationRole and col == 0 and row.issues:
            if self._icon is None:
                self._icon = warning_icon()
            return self._icon
        return None

    def blank_placeholder(self) -> str:
        return self.tr("escribe aquí el nombre corto para añadir...")

    def _blank_data(self, col: int, role: int) -> object:
        if col != 0:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.blank_placeholder()
        if role == Qt.ItemDataRole.EditRole:
            return ""
        if role == Qt.ItemDataRole.DecorationRole:
            return icon("add")
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._new_error or self.tr(
                "Escribe un nombre corto y pulsa Intro para añadir una fila nueva"
            )
        if role == Qt.ItemDataRole.BackgroundRole and self._new_error:
            return QColor(ERROR_COLOR)
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor("#9ca3af")
        return None

    def flags(self, index: AnyIndex) -> Qt.ItemFlag:
        if not index.isValid() or self.table is None:
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        spec = self.columns[index.column()]
        if self.is_blank_row(index.row()):
            return base | Qt.ItemFlag.ItemIsEditable if index.column() == 0 else base
        if not spec.editable:
            return base
        if spec.value_type is ValueType.BOOL:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base | Qt.ItemFlag.ItemIsEditable

    def setData(self, index: AnyIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or self.table is None or not self.bridge.has_session:
            return False
        fila, col = index.row(), index.column()
        if self.is_blank_row(fila):
            return role == Qt.ItemDataRole.EditRole and col == 0 and self.add(str(value or ""))
        spec = self.columns[col]
        if role == Qt.ItemDataRole.CheckStateRole and spec.value_type is ValueType.BOOL:
            texto = "x" if is_checked(value) else ""
        elif role == Qt.ItemDataRole.EditRole:
            texto = "" if value is None else str(value)
        else:
            return False
        return self.set_cell(fila, spec.field, texto)

    # --- ediciones ----------------------------------------------------------- #

    def set_cell(self, row: int, field: str, text: str) -> bool:
        """Edita una celda a través del puente; en rojo si la Fachada la rechaza."""
        clave = self.key_at(row)
        col = next((i for i, c in enumerate(self.columns) if c.field == field), -1)
        if clave is None or col < 0:
            return False
        actual = self._rows[row].cells[col]
        if text == actual and (clave, field) not in self._errors:
            return False
        svc, kind = self.bridge.service, self.kind
        resultado = self.bridge.edit(
            lambda: svc.set_master_cell(self.bridge.session, kind, clave, field, text)
        )
        indice = self.index(row, col)
        if resultado.ok:
            self._errors.pop((clave, field), None)
            celdas = list(self._rows[row].cells)
            celdas[col] = text
            previa = self._rows[row]
            self._rows[row] = MasterRow(previa.key, tuple(celdas), previa.issues)
        else:
            self._errors[(clave, field)] = self.tr("Valor rechazado «{0}»: {1}").format(
                text, resultado.message
            )
            self.edit_failed.emit(resultado.message)
        self.dataChanged.emit(indice, indice)
        return resultado.ok

    def add(self, entity_id: str) -> bool:
        ident = entity_id.strip()
        if not ident or not self.bridge.has_session:
            return False
        svc, kind = self.bridge.service, self.kind
        resultado = self.bridge.edit(lambda: svc.add_master(self.bridge.session, kind, ident))
        self._new_error = "" if resultado.ok else resultado.message
        if not resultado.ok:
            self.edit_failed.emit(resultado.message)
            indice = self.index(len(self._rows), 0)
            self.dataChanged.emit(indice, indice)
        return resultado.ok

    def error_of_new(self) -> str:
        """Motivo del último alta rechazada ("" si no hay)."""
        return self._new_error

    def remove(self, key: str) -> EditResult:
        svc, kind = self.bridge.service, self.kind
        resultado = self.bridge.edit(lambda: svc.remove_master(self.bridge.session, kind, key))
        if not resultado.ok:
            self.edit_failed.emit(resultado.message)
        return resultado


class MasterFilterProxy(QSortFilterProxyModel):
    """Filtro de texto (todas las columnas) y orden; la fila en blanco siempre al final."""

    def __init__(self, source: MasterTableModel) -> None:
        super().__init__()
        self._source = source
        self._text = ""
        self.setSourceModel(source)

    @property
    def filter_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self.beginFilterChange()
        self._text = text.strip().casefold()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: AnyIndex) -> bool:
        if not self._text or self._source.is_blank_row(source_row):
            return True
        fila = self._source.row_at(source_row)
        return fila is not None and any(self._text in c.casefold() for c in fila.cells)

    def lessThan(self, source_left: AnyIndex, source_right: AnyIndex) -> bool:
        descendente = self.sortOrder() == Qt.SortOrder.DescendingOrder
        if self._source.is_blank_row(source_left.row()):
            return descendente
        if self._source.is_blank_row(source_right.row()):
            return not descendente
        a = str(source_left.data(Qt.ItemDataRole.EditRole) or "")
        b = str(source_right.data(Qt.ItemDataRole.EditRole) or "")
        if a.lstrip("-").isdigit() and b.lstrip("-").isdigit():
            return int(a) < int(b)
        return a.casefold() < b.casefold()


# --------------------------------------------------------------------------- #
# Widget
# --------------------------------------------------------------------------- #


class MasterDataGrid(QWidget):
    """Ventana genérica de datos maestros sobre un `MasterKind`."""

    def __init__(
        self, bridge: FacadeBridge, kind: MasterKind, window_key: str | None = None
    ) -> None:
        super().__init__()
        self.bridge = bridge
        self.kind = kind
        self.window_key = window_key or kind.value
        self.selection_kind = SELECTION_KIND.get(kind)
        self._restoring = False
        self._syncing = False
        self._sized = False

        self.model = MasterTableModel(bridge, kind)
        self.proxy = MasterFilterProxy(self.model)

        # --- barra de herramientas -------------------------------------------- #
        self.add_button = tool_button("add", self.start_add)
        self.remove_button = tool_button("delete", self.remove_selected)
        self.requests_button = tool_button("requests", self.open_requests)
        self.requests_button.setVisible(self.selection_kind is not None)
        self.columns_menu = QMenu(self)
        self.columns_menu.menuAction().setIcon(icon("columns"))
        self.columns_menu.aboutToShow.connect(lambda: self._fill_columns_menu(self.columns_menu))
        self.columns_button = tool_button("columns")
        self.columns_button.setMenu(self.columns_menu)
        self.columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.filter_edit = QLineEdit()
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMaximumWidth(320)
        self.search_action = self.filter_edit.addAction(
            icon("search"), QLineEdit.ActionPosition.LeadingPosition
        )
        self.filter_edit.textChanged.connect(self._on_filter)
        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #4b5563;")

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(ChoiceDelegate(self._choices, self.view))
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.view.setAlternatingRowColors(True)
        self.view.verticalHeader().setDefaultSectionSize(22)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._row_menu)
        header = self.view.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)
        header.sectionMoved.connect(lambda *_: self.save_layout())
        header.sectionResized.connect(lambda *_: self.save_layout())
        self.view.setSortingEnabled(True)
        self.hint = EmptyHint(self.view)

        self.add_action = make_action(self, "add", self.start_add)
        self.remove_action = make_action(self, "delete", self.remove_selected)
        self.remove_action.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        self.remove_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.view.addAction(self.remove_action)
        self.requests_action = make_action(self, "requests", self.open_requests)

        self.message = Banner("error")
        self.message.hide()

        barra = QHBoxLayout()
        barra.setSpacing(4)
        for boton in (
            self.add_button,
            self.remove_button,
            self.requests_button,
            self.columns_button,
        ):
            barra.addWidget(boton)
        barra.addSpacing(12)
        barra.addWidget(self.filter_edit, 1)
        barra.addStretch(0)
        barra.addWidget(self.count_label)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)
        raiz.addLayout(barra)
        raiz.addWidget(self.view, 1)
        raiz.addWidget(self.message)

        self.model.edit_failed.connect(self.show_message)
        selection = self.view.selectionModel()
        selection.currentRowChanged.connect(self._on_current_row)
        selection.selectionChanged.connect(lambda *_: self._update_buttons())
        bridge.refreshed.connect(self.refresh)
        bridge.project_opened.connect(self.model.clear_errors)
        bridge.selection_changed.connect(self._on_selection)
        bridge.language_changed.connect(lambda _lang: self._retranslate())

        self._retranslate()
        self.refresh()

    # --- carga y disposición ---------------------------------------------------- #

    def refresh(self) -> None:
        """Recarga la tabla y vuelve a aplicar la disposición guardada."""
        previo = self._restoring
        self._restoring = True
        try:
            self.model.reload()
            if self.model.table is not None and not self.restore_layout() and not self._sized:
                # Primera carga sin disposición guardada: anchos según el contenido
                # visible (solo una vez; con cientos de filas es lo más caro).
                self._sized = True
                self.view.horizontalHeader().resizeSections(QHeaderView.ResizeMode.ResizeToContents)
            if self.model.table is not None and not self.model.rows:
                # Tabla vacía: que se lea entero el texto de la fila en blanco.
                cabecera = self.view.horizontalHeader()
                cabecera.resizeSection(0, max(cabecera.sectionSize(0), 280))
        finally:
            self._restoring = previo
        self._update_count()
        self._update_hint()
        self._update_buttons()
        if self.bridge.selection is not None:
            self._on_selection(*self.bridge.selection)

    def _update_count(self) -> None:
        total = len(self.model.rows)
        visibles = len(self.visible_keys()) if self.proxy.filter_text else total
        if visibles != total:
            texto = self.tr("{0} de {1} filas").format(visibles, total)
        else:
            texto = self.tr("{0} filas").format(total)
        self.count_label.setText(texto)

    def _empty_text(self) -> str:
        textos = {
            MasterKind.CLASSES: self.tr(
                "Aún no hay clases. Pulsa Añadir o escribe un nombre corto en la fila vacía."
            ),
            MasterKind.TEACHERS: self.tr(
                "Aún no hay profesores. Pulsa Añadir o escribe un nombre corto en la fila vacía."
            ),
            MasterKind.ROOMS: self.tr(
                "Aún no hay aulas. Pulsa Añadir o escribe un nombre corto en la fila vacía."
            ),
            MasterKind.SUBJECTS: self.tr(
                "Aún no hay materias. Pulsa Añadir o escribe un nombre corto en la fila vacía."
            ),
            MasterKind.DEPARTMENTS: self.tr(
                "Aún no hay departamentos. Pulsa Añadir o escribe un nombre corto en la fila vacía."
            ),
            MasterKind.STUDENT_GROUPS: self.tr(
                "Aún no hay grupos de alumnos. Pulsa Añadir o escribe un nombre corto "
                "en la fila vacía."
            ),
        }
        return textos[self.kind]

    def hint_text(self) -> str:
        """Texto de ayuda que se ve sobre la tabla ("" si hay filas visibles)."""
        if self.model.table is None:
            return self.tr("Abre o crea un proyecto para ver y editar sus datos.")
        if not self.model.rows:
            return self._empty_text()
        if self.proxy.filter_text and not self.visible_keys():
            return self.tr(
                "Ninguna fila contiene «{0}». Borra el filtro para verlas todas."
            ).format(self.filter_edit.text().strip())
        return ""

    def _update_hint(self) -> None:
        self.hint.show_hint(self.hint_text())

    def _update_buttons(self) -> None:
        abierto = self.model.table is not None
        hay_fila = self.current_key() is not None
        self.add_button.setEnabled(abierto)
        self.add_action.setEnabled(abierto)
        self.remove_button.setEnabled(hay_fila)
        self.remove_action.setEnabled(hay_fila)
        self.requests_button.setEnabled(hay_fila)
        self.requests_action.setEnabled(hay_fila)
        self.columns_button.setEnabled(abierto)

    def _settings_key(self) -> str:
        return f"layouts/{self.window_key}/header"

    def save_layout(self) -> None:
        """Guarda orden, anchos y columnas ocultas de esta ventana."""
        if self._restoring or self.model.table is None:
            return
        ajustes = layout_settings()
        ajustes.setValue(self._settings_key(), self.view.horizontalHeader().saveState())
        ajustes.sync()

    def restore_layout(self) -> bool:
        if self.model.table is None:
            return False
        valor = layout_settings().value(self._settings_key())
        if not isinstance(valor, QByteArray) or valor.isEmpty():
            return False
        previo = self._restoring
        self._restoring = True
        try:
            return self.view.horizontalHeader().restoreState(valor)
        finally:
            self._restoring = previo

    def set_column_hidden(self, column: int, hidden: bool) -> None:
        """Muestra u oculta una columna (la del nombre corto nunca se oculta)."""
        if column == 0 and hidden:
            return
        self.view.horizontalHeader().setSectionHidden(column, hidden)
        self.save_layout()

    def move_column(self, logical: int, visual: int) -> None:
        header = self.view.horizontalHeader()
        header.moveSection(header.visualIndex(logical), visual)

    def _header_menu(self, pos: QPoint) -> None:
        self.header_menu().exec(self.view.horizontalHeader().mapToGlobal(pos))

    def header_menu(self) -> QMenu:
        """Menú de columnas (mostrar/ocultar), también usado por las pruebas."""
        menu = QMenu(self)
        self._fill_columns_menu(menu)
        return menu

    def _fill_columns_menu(self, menu: QMenu) -> None:
        """Una casilla por columna (marcada = visible) y Restablecer columnas."""
        menu.clear()
        menu.setToolTipsVisible(True)
        header = self.view.horizontalHeader()
        for i, spec in enumerate(self.model.columns):
            accion = menu.addAction(spec.title(self.bridge.language))
            accion.setCheckable(True)
            accion.setChecked(not header.isSectionHidden(i))
            accion.setEnabled(i != 0)
            ayuda = self.model.field_help(spec.field)
            accion.setToolTip(
                self.tr("Muestra u oculta la columna: {0}").format(ayuda or spec.field)
            )
            accion.toggled.connect(lambda visible, c=i: self.set_column_hidden(c, not visible))
        menu.addSeparator()
        restablecer = menu.addAction(icon("undo"), self.tr("Restablecer columnas"))
        restablecer.setToolTip(self.tr("Vuelve a mostrar todas las columnas en su orden original"))
        restablecer.triggered.connect(self.reset_layout)

    def reset_layout(self) -> None:
        header = self.view.horizontalHeader()
        previo = self._restoring
        self._restoring = True
        try:
            for logico in range(header.count()):
                header.setSectionHidden(logico, False)
                header.moveSection(header.visualIndex(logico), logico)
            header.resizeSections(QHeaderView.ResizeMode.ResizeToContents)
        finally:
            self._restoring = previo
        self.save_layout()

    # --- filtro, selección ------------------------------------------------------- #

    def set_filter(self, text: str) -> None:
        self.filter_edit.setText(text)

    def _on_filter(self, text: str) -> None:
        self.proxy.set_text(text)
        self._update_count()
        self._update_hint()

    def visible_keys(self) -> list[str]:
        claves: list[str] = []
        for fila in range(self.proxy.rowCount()):
            clave = self.model.key_at(self.proxy.mapToSource(self.proxy.index(fila, 0)).row())
            if clave is not None:
                claves.append(clave)
        return claves

    def current_key(self) -> str | None:
        indice = self.view.currentIndex()
        if not indice.isValid():
            return None
        return self.model.key_at(self.proxy.mapToSource(indice).row())

    def select_key(self, key: str) -> bool:
        fila = self.model.row_of(key)
        if fila < 0:
            return False
        indice = self.proxy.mapFromSource(self.model.index(fila, 0))
        if not indice.isValid():
            return False
        self.view.setCurrentIndex(indice)
        self.view.scrollTo(indice)
        return True

    def _on_current_row(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self._update_buttons()
        if self._syncing or self.selection_kind is None or not current.isValid():
            return
        clave = self.model.key_at(self.proxy.mapToSource(current).row())
        if clave is not None:
            self.bridge.select(self.selection_kind, clave)

    def _on_selection(self, kind: str, entity_id: str) -> None:
        if kind != self.selection_kind or self.current_key() == entity_id:
            return
        self._syncing = True
        try:
            self.select_key(entity_id)
        finally:
            self._syncing = False

    # --- órdenes ----------------------------------------------------------------- #

    def _choices(self, index: AnyIndex) -> tuple[str, ...] | None:
        fuente = self.proxy.mapToSource(index) if index.model() is self.proxy else index
        if self.model.is_blank_row(fuente.row()):
            return None
        return self.model.references(fuente.column())

    def blank_index(self) -> QModelIndex:
        """Celda del nombre corto de la fila en blanco, en la vista."""
        if self.model.table is None:
            return QModelIndex()
        return self.proxy.mapFromSource(self.model.index(len(self.model.rows), 0))

    def start_add(self) -> bool:
        """Añadir: lleva el cursor a la fila en blanco y abre su editor."""
        if self.model.table is None:
            return False
        if self.filter_edit.text():
            self.filter_edit.clear()
        indice = self.blank_index()
        if not indice.isValid():
            return False
        self.view.setFocus()
        self.view.scrollTo(indice)
        self.view.setCurrentIndex(indice)
        self.view.edit(indice)
        return True

    def add_entity(self, entity_id: str) -> bool:
        """Añade una fila con ese nombre corto y la selecciona."""
        if not self.model.add(entity_id):
            self.show_message(self.model.error_of_new())
            return False
        self.message.hide()
        self.refresh()
        self.select_key(entity_id.strip())
        return True

    def remove_selected(self) -> bool:
        """Borra las filas seleccionadas; si alguna se usa, muestra el motivo."""
        claves: list[str] = []
        for indice in self.view.selectionModel().selectedRows():
            clave = self.model.key_at(self.proxy.mapToSource(indice).row())
            if clave is not None:
                claves.append(clave)
        if not claves:
            clave = self.current_key()
            if clave is not None:
                claves.append(clave)
        todo_ok = bool(claves)
        for clave in claves:
            todo_ok = self.model.remove(clave).ok and todo_ok
        if todo_ok:
            self.message.hide()
        return todo_ok

    def open_requests(self) -> None:
        """Abre Deseos de tiempo enfocado en la entidad de la fila actual."""
        clave = self.current_key()
        if clave is None or self.selection_kind is None:
            return
        principal = self.window()
        if hasattr(principal, "show_window"):
            principal.show_window(REQUESTS_KEY)
        self.bridge.select(self.selection_kind, clave)

    def show_message(self, text: str) -> None:
        self.message.show_message(text, "error")
        if text:
            self.bridge.status.emit(text)

    def row_menu(self) -> QMenu:
        """Menú contextual de una fila (también para las pruebas)."""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        menu.addAction(self.add_action)
        if self.selection_kind is not None:
            menu.addAction(self.requests_action)
        menu.addSeparator()
        menu.addAction(self.remove_action)
        return menu

    def _row_menu(self, pos: QPoint) -> None:
        self.row_menu().exec(self.view.viewport().mapToGlobal(pos))

    # --- idioma ------------------------------------------------------------------- #

    def _retranslate(self) -> None:
        self.filter_edit.setPlaceholderText(self.tr("Filtrar por cualquier columna..."))
        self.filter_edit.setToolTip(
            self.tr("Escribe para ver solo las filas que contienen ese texto")
        )
        self.search_action.setToolTip(self.tr("Filtro: muestra solo las filas que coinciden"))
        set_texts(
            self.add_button,
            self.tr("Añadir"),
            self.tr("Añade una fila nueva: escribe su nombre corto en la fila vacía y pulsa Intro"),
        )
        set_texts(
            self.add_action,
            self.tr("Añadir"),
            self.tr("Añade una fila nueva escribiendo su nombre corto"),
        )
        set_texts(
            self.remove_button,
            self.tr("Borrar"),
            self.tr("Borra las filas seleccionadas (Supr); si alguna se usa, explica dónde"),
        )
        set_texts(
            self.remove_action,
            self.tr("Borrar"),
            self.tr("Borra las filas seleccionadas; se puede deshacer"),
        )
        set_texts(
            self.requests_button,
            self.tr("Deseos"),
            self.tr("Abre los deseos de tiempo (cuándo sí y cuándo no) de la fila seleccionada"),
        )
        set_texts(
            self.requests_action,
            self.tr("Deseos de tiempo..."),
            self.tr("Abre los deseos de tiempo de esta fila"),
        )
        set_texts(
            self.columns_button,
            self.tr("Columnas"),
            self.tr("Elige qué columnas se ven; también con clic derecho en la cabecera"),
        )
        self.columns_menu.menuAction().setText(self.tr("Columnas"))
        self.columns_menu.menuAction().setToolTip(self.tr("Muestra u oculta columnas"))
        self._update_count()
        self._update_hint()
        n = self.model.columnCount()
        if n:
            self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, n - 1)
