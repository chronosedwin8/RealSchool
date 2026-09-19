"""Ventana Sustituciones: el parte del día cuando falta alguien.

El horario es de la semana; esta ventana trabaja sobre un **día concreto**. Se
elige la fecha y se ve, de un vistazo:

- las **ausencias** vigentes ese día (profesores, clases o aulas), con alta y baja;
- las **clases afectadas** por esas ausencias y las decisiones ya tomadas;
- los **contadores** de sustituciones de cada profesor, para repartir con justicia.

Para cada clase afectada se puede pedir "Proponer sustituto": la Fachada
devuelve los profesores posibles ordenados de mejor a peor, cada uno con la
razón de su puesto (ya está en el centro, da la materia, cuántas sustituciones
lleva...). También se puede suprimir la clase o cambiarle el aula.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import EditResult, MasterKind
from scheduling_platform.application.untis.substitution import (
    AbsenceRow,
    CandidateRow,
    DayReport,
    DayRow,
    SubstitutionMixin,
)

from ..icons import icon
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import day_name
from ..widgets.master_grid import entity_ids
from ..widgets.uikit import Banner, EmptyHint, tool_button

#: Formato Untis de las fechas (`AAAAMMDD`).
DATE_FORMAT = "yyyyMMdd"

#: Tipos de entidad que pueden faltar, en el orden del desplegable.
ABSENCE_KINDS: tuple[str, ...] = ("teacher", "class", "room")

#: Icono y tipo de datos maestros de cada tipo de ausencia.
KIND_ICONS: dict[str, str] = {"teacher": "teachers", "class": "classes", "room": "rooms"}
KIND_MASTER: dict[str, MasterKind] = {
    "teacher": MasterKind.TEACHERS,
    "class": MasterKind.CLASSES,
    "room": MasterKind.ROOMS,
}


def _cell(text: str, tooltip: str = "") -> QTableWidgetItem:
    """Celda de solo lectura con su ayuda emergente."""
    celda = QTableWidgetItem(text)
    celda.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if tooltip:
        celda.setToolTip(tooltip)
    return celda


def _table(columns: int) -> QTableWidget:
    """Tabla de solo lectura por filas, como el resto de las listas."""
    tabla = QTableWidget(0, columns)
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tabla.verticalHeader().setVisible(False)
    tabla.horizontalHeader().setStretchLastSection(True)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    return tabla


class AbsenceDialog(QDialog):
    """Alta de una ausencia: quién falta, qué días y de qué hora a qué hora."""

    def __init__(self, bridge: FacadeBridge, day: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self.kind_combo = QComboBox()
        for kind in ABSENCE_KINDS:
            self.kind_combo.addItem(icon(KIND_ICONS[kind]), kind, kind)
        self.kind_combo.currentIndexChanged.connect(lambda _i: self._load_entities())
        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(140)
        fecha = QDate.fromString(day, DATE_FORMAT)
        self.begin = QDateEdit(fecha if fecha.isValid() else QDate.currentDate())
        self.end = QDateEdit(fecha if fecha.isValid() else QDate.currentDate())
        for caja in (self.begin, self.end):
            caja.setCalendarPopup(True)
            caja.setDisplayFormat("dd/MM/yyyy")
        self.first_period = QSpinBox()
        self.last_period = QSpinBox()
        for horas in (self.first_period, self.last_period):
            horas.setRange(0, 20)
            horas.setSpecialValueText("-")
        self.reason = QLineEdit()

        self.labels: dict[str, QLabel] = {}
        formulario = QFormLayout()
        for clave, campo in (
            ("kind", self.kind_combo),
            ("entity", self.entity_combo),
            ("begin", self.begin),
            ("end", self.end),
            ("first", self.first_period),
            ("last", self.last_period),
            ("reason", self.reason),
        ):
            etiqueta = QLabel()
            self.labels[clave] = etiqueta
            formulario.addRow(etiqueta, campo)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addLayout(formulario)
        capa.addWidget(self.buttons)
        self._load_entities()
        self._retranslate()

    def _load_entities(self) -> None:
        self.entity_combo.clear()
        self.entity_combo.addItems(list(entity_ids(self.bridge, KIND_MASTER[self.kind])))

    @property
    def kind(self) -> str:
        return str(self.kind_combo.currentData() or ABSENCE_KINDS[0])

    @property
    def entity(self) -> str:
        return self.entity_combo.currentText()

    def values(self) -> tuple[str, str, str, str, int | None, int | None, str]:
        """Lo que hay que pasar a la Fachada."""
        primera = self.first_period.value() or None
        ultima = self.last_period.value() or None
        return (
            self.kind,
            self.entity,
            self.begin.date().toString(DATE_FORMAT),
            self.end.date().toString(DATE_FORMAT),
            primera,
            ultima,
            self.reason.text(),
        )

    def _retranslate(self) -> None:
        self.setWindowTitle(self.tr("Nueva ausencia"))
        nombres = {
            "teacher": self.tr("Profesor"),
            "class": self.tr("Clase"),
            "room": self.tr("Aula"),
        }
        for i, kind in enumerate(ABSENCE_KINDS):
            self.kind_combo.setItemText(i, nombres[kind])
        textos = {
            "kind": (self.tr("Falta un:"), self.tr("Qué falta: un profesor, una clase o un aula")),
            "entity": (self.tr("Quién:"), self.tr("El profesor, la clase o el aula que falta")),
            "begin": (self.tr("Desde el día:"), self.tr("Primer día de la ausencia")),
            "end": (self.tr("Hasta el día:"), self.tr("Último día de la ausencia (incluido)")),
            "first": (
                self.tr("Desde la hora:"),
                self.tr("Primera hora del primer día; - = desde el principio de la jornada"),
            ),
            "last": (
                self.tr("Hasta la hora:"),
                self.tr("Última hora del último día; - = hasta el final de la jornada"),
            ),
            "reason": (
                self.tr("Motivo:"),
                self.tr("Por qué falta: enfermedad, curso, excursión..."),
            ),
        }
        for clave, (texto, ayuda) in textos.items():
            self.labels[clave].setText(texto)
            self.labels[clave].setToolTip(ayuda)


class CandidatesDialog(QDialog):
    """Candidatos a cubrir una clase, del mejor al peor, con su explicación."""

    def __init__(self, rows: tuple[CandidateRow, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows = rows
        self.table = _table(4)
        self.table.setRowCount(len(rows))
        for i, fila in enumerate(rows):
            self.table.setItem(i, 0, _cell(fila.teacher, fila.name))
            self.table.setItem(i, 1, _cell(fila.name))
            self.table.setItem(i, 2, _cell(str(fila.score)))
            self.table.setItem(i, 3, _cell(fila.reason, fila.reason))
        if rows:
            self.table.selectRow(0)
        self.table.doubleClicked.connect(lambda _i: self.accept())
        self.hint = Banner("tip")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addWidget(self.table, 1)
        capa.addWidget(self.hint)
        capa.addWidget(self.buttons)
        self.resize(560, 360)
        self._retranslate()

    @property
    def teacher(self) -> str:
        """Profesor elegido (vacío si no hay ninguno)."""
        fila = self.table.currentRow()
        return self.rows[fila].teacher if 0 <= fila < len(self.rows) else ""

    def _retranslate(self) -> None:
        self.setWindowTitle(self.tr("Proponer sustituto"))
        self.table.setHorizontalHeaderLabels(
            [self.tr("Profesor"), self.tr("Nombre"), self.tr("Puntos"), self.tr("Por qué")]
        )
        self.hint.setText(
            self.tr(
                "El primero de la lista es el mejor: se prefiere a quien ya está en el centro, "
                "luego a quien da la materia o al grupo, y después a quien menos sustituciones "
                "lleva. Nunca se propone a quien tiene clase o está ausente."
            )
        )


class SubstitutionWindow(QWidget):
    """Parte del día: ausencias, clases afectadas, sustitutos y contadores."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.report: DayReport | None = None
        self.rows: tuple[DayRow, ...] = ()
        self.absence_rows: tuple[AbsenceRow, ...] = ()

        self.date_label = QLabel()
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.dateChanged.connect(lambda _d: self.refresh())
        self.prev_button = tool_button("undo", self.previous_day, text_beside=False)
        self.next_button = tool_button("redo", self.next_day, text_beside=False)
        self.weekday_label = QLabel()
        self.holiday_button = tool_button("grid_remove", self.toggle_holiday)

        self.absence_box = QGroupBox()
        self.absence_table = _table(5)
        self.absence_empty = EmptyHint(self.absence_table)
        self.add_absence_button = tool_button("add", self.add_absence_dialog)
        self.remove_absence_button = tool_button("delete", self.remove_absence)
        botones_ausencia = QHBoxLayout()
        botones_ausencia.addWidget(self.add_absence_button)
        botones_ausencia.addWidget(self.remove_absence_button)
        botones_ausencia.addStretch(1)
        capa_ausencias = QVBoxLayout(self.absence_box)
        capa_ausencias.addWidget(self.absence_table, 1)
        capa_ausencias.addLayout(botones_ausencia)

        self.day_box = QGroupBox()
        self.day_table = _table(8)
        self.day_empty = EmptyHint(self.day_table)
        self.propose_button = tool_button("optimize", self.propose)
        self.cancel_button = tool_button("unplace", self.cancel_lesson)
        self.room_button = tool_button("rooms", self.change_room_dialog)
        self.clear_button = tool_button("remove", self.clear_decision)
        botones_dia = QHBoxLayout()
        for boton in (
            self.propose_button,
            self.cancel_button,
            self.room_button,
            self.clear_button,
        ):
            botones_dia.addWidget(boton)
        botones_dia.addStretch(1)
        capa_dia = QVBoxLayout(self.day_box)
        capa_dia.addWidget(self.day_table, 1)
        capa_dia.addLayout(botones_dia)

        self.counter_box = QGroupBox()
        self.counter_table = _table(4)
        capa_contadores = QVBoxLayout(self.counter_box)
        capa_contadores.addWidget(self.counter_table, 1)

        self.hint = Banner("tip")
        barra = QHBoxLayout()
        barra.addWidget(self.date_label)
        barra.addWidget(self.prev_button)
        barra.addWidget(self.date_edit)
        barra.addWidget(self.next_button)
        barra.addWidget(self.weekday_label)
        barra.addSpacing(16)
        barra.addWidget(self.holiday_button)
        barra.addStretch(1)
        centro = QHBoxLayout()
        centro.addWidget(self.absence_box, 2)
        centro.addWidget(self.day_box, 5)
        centro.addWidget(self.counter_box, 2)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)
        raiz.addLayout(barra)
        raiz.addLayout(centro, 1)
        raiz.addWidget(self.hint)

        bridge.refreshed.connect(self.refresh)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()

    # --- estado -------------------------------------------------------------- #

    @property
    def facade(self) -> SubstitutionMixin:
        """La Fachada, que ya trae el módulo de sustituciones."""
        return self.bridge.service

    @property
    def date(self) -> str:
        """Fecha elegida en formato Untis `AAAAMMDD`."""
        return str(self.date_edit.date().toString(DATE_FORMAT))

    def set_date(self, day: str) -> None:
        """Muestra el parte de esa fecha `AAAAMMDD`."""
        fecha = QDate.fromString(day, DATE_FORMAT)
        if fecha.isValid():
            self.date_edit.setDate(fecha)

    def previous_day(self) -> None:
        self.date_edit.setDate(self.date_edit.date().addDays(-1))

    def next_day(self) -> None:
        self.date_edit.setDate(self.date_edit.date().addDays(1))

    def current_row(self) -> DayRow | None:
        """Clase seleccionada en el parte del día."""
        fila = self.day_table.currentRow()
        return self.rows[fila] if 0 <= fila < len(self.rows) else None

    def current_absence(self) -> AbsenceRow | None:
        fila = self.absence_table.currentRow()
        return self.absence_rows[fila] if 0 <= fila < len(self.absence_rows) else None

    # --- carga ---------------------------------------------------------------- #

    def refresh(self) -> None:
        """Recarga el parte del día elegido."""
        if not self.bridge.has_session:
            self.report = None
            self.rows = ()
            self.absence_rows = ()
            self.absence_table.setRowCount(0)
            self.day_table.setRowCount(0)
            self.counter_table.setRowCount(0)
            self.day_empty.show_hint(self.tr("Sin proyecto: abre o crea uno."))
            self.absence_empty.show_hint(self.tr("Sin proyecto."))
            self.weekday_label.setText("")
            self._update_holiday_button()
            return
        sesion = self.bridge.session
        parte = self.facade.day_report(sesion, self.date)
        self.report = parte
        self.rows = parte.rows
        self.absence_rows = parte.absences
        self.weekday_label.setText(self._weekday_text(parte))
        self._fill_absences()
        self._fill_day()
        self._fill_counters()
        self._update_holiday_button()

    def _weekday_text(self, parte: DayReport) -> str:
        nombre = day_name(parte.weekday, self.bridge.language) if parte.weekday else ""
        if parte.is_holiday:
            return self.tr("{0} - sin clase: {1}").format(nombre, parte.holiday)
        if parte.pending:
            return self.tr("{0} - {1} clase(s) por resolver").format(nombre, parte.pending)
        return nombre

    def _fill_absences(self) -> None:
        self.absence_table.setRowCount(len(self.absence_rows))
        for i, fila in enumerate(self.absence_rows):
            self.absence_table.setItem(i, 0, _cell(fila.entity_id, fila.name))
            self.absence_table.setItem(i, 1, _cell(self._kind_name(fila.entity_kind)))
            self.absence_table.setItem(i, 2, _cell(self._pretty(fila.begin)))
            self.absence_table.setItem(i, 3, _cell(self._pretty(fila.end)))
            self.absence_table.setItem(i, 4, _cell(fila.reason, fila.periods_label))
        if not self.absence_rows:
            self.absence_empty.show_hint(self.tr("Nadie falta este día."))
        else:
            self.absence_empty.show_hint("")

    def _fill_day(self) -> None:
        self.day_table.setRowCount(len(self.rows))
        for i, fila in enumerate(self.rows):
            self.day_table.setItem(i, 0, _cell(str(fila.period)))
            self.day_table.setItem(i, 1, _cell(str(fila.lesson)))
            self.day_table.setItem(i, 2, _cell(fila.subject))
            self.day_table.setItem(i, 3, _cell(", ".join(fila.classes)))
            self.day_table.setItem(i, 4, _cell(", ".join(fila.teachers)))
            self.day_table.setItem(i, 5, _cell(fila.new_room or ", ".join(fila.rooms)))
            self.day_table.setItem(i, 6, _cell(fila.kind_label or "", fila.reason))
            self.day_table.setItem(i, 7, _cell(fila.substitute or "", fila.reason))
        if not self.rows:
            mensaje = self.report.message if self.report is not None else ""
            self.day_empty.show_hint(mensaje or self.tr("Ningún cambio este día."))
        else:
            self.day_empty.show_hint("")
            if self.day_table.currentRow() < 0:
                self.day_table.selectRow(0)

    def _fill_counters(self) -> None:
        filas = self.facade.substitution_counters(self.bridge.session)
        self.counter_table.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            self.counter_table.setItem(i, 0, _cell(fila.teacher, fila.name))
            self.counter_table.setItem(i, 1, _cell(str(fila.count)))
            self.counter_table.setItem(i, 2, _cell(str(fila.assigned)))
            self.counter_table.setItem(i, 3, _cell(str(fila.lock)))

    def _kind_name(self, kind: str) -> str:
        return {
            "teacher": self.tr("Profesor"),
            "class": self.tr("Clase"),
            "room": self.tr("Aula"),
        }.get(kind, kind)

    @staticmethod
    def _pretty(day: str) -> str:
        """`AAAAMMDD` -> `DD/MM/AAAA` (lo que lee una persona)."""
        fecha = QDate.fromString(day, DATE_FORMAT)
        return str(fecha.toString("dd/MM/yyyy")) if fecha.isValid() else day

    # --- ausencias ------------------------------------------------------------- #

    def add_absence(
        self,
        kind: str,
        entity: str,
        begin: str,
        end: str = "",
        first_period: int | None = None,
        last_period: int | None = None,
        reason: str = "",
    ) -> EditResult:
        """Da de alta una ausencia a través de la Fachada."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        facade, sesion = self.facade, self.bridge.session
        resultado = self.bridge.edit(
            lambda: facade.add_absence(
                sesion, kind, entity, begin, end, first_period, last_period, reason
            )
        )
        self.refresh()
        return resultado

    def add_absence_dialog(self) -> EditResult:
        """Pregunta los datos de la ausencia y la da de alta."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        dialogo = AbsenceDialog(self.bridge, self.date, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return EditResult.failure("")
        return self.add_absence(*dialogo.values())

    def _update_holiday_button(self) -> None:
        """El botón dice lo que va a hacer: marcar el día o devolverle la clase."""
        festivo = self.is_holiday()
        self.holiday_button.setText(
            self.tr("Devolver la clase") if festivo else self.tr("Día sin clase")
        )
        self.holiday_button.setToolTip(
            self.tr("Este día está marcado como día sin clase: quítale la marca")
            if festivo
            else self.tr("Marca este día como festivo o jornada sin clase")
        )
        self.holiday_button.setEnabled(self.bridge.has_session)

    def is_holiday(self) -> bool:
        """`True` si el día elegido está marcado como día sin clase."""
        if not self.bridge.has_session:
            return False
        dia = self.date
        return any(f.begin <= dia <= f.end for f in self.facade.holidays(self.bridge.session))

    def toggle_holiday(self) -> EditResult:
        """Marca el día elegido como día sin clase, o le quita la marca.

        Es el calendario del curso en su forma más simple: un día marcado no
        tiene clases, así que no hay nada que sustituir en él.
        """
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        facade, sesion, dia = self.facade, self.bridge.session, self.date
        festivo = next((f for f in facade.holidays(sesion) if f.begin <= dia <= f.end), None)
        if festivo is not None:
            resultado = self.bridge.edit(lambda: facade.remove_holiday(sesion, festivo.id))
        else:
            nombre = self.tr("Día sin clase")
            resultado = self.bridge.edit(lambda: facade.add_holiday(sesion, nombre, dia))
        self.refresh()
        return resultado

    def remove_absence(self) -> EditResult:
        """Quita la ausencia seleccionada (y las decisiones que venían de ella)."""
        fila = self.current_absence()
        if fila is None:
            return EditResult.failure(self.tr("Elige una ausencia de la lista"))
        facade, sesion = self.facade, self.bridge.session
        resultado = self.bridge.edit(lambda: facade.remove_absence(sesion, fila.id))
        self.refresh()
        return resultado

    # --- decisiones -------------------------------------------------------------- #

    def candidates(self) -> tuple[CandidateRow, ...]:
        """Candidatos a cubrir la clase seleccionada, de mejor a peor."""
        fila = self.current_row()
        if fila is None or not self.bridge.has_session:
            return ()
        return self.facade.substitute_candidates(
            self.bridge.session, self.date, fila.period, fila.lesson
        )

    def propose(self) -> EditResult:
        """Muestra los candidatos ordenados y asigna el elegido."""
        fila = self.current_row()
        if fila is None:
            return EditResult.failure(self.tr("Elige una clase del parte del día"))
        filas = self.candidates()
        if not filas:
            return EditResult.failure(self.tr("Nadie está libre esa hora"))
        dialogo = CandidatesDialog(filas, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted or not dialogo.teacher:
            return EditResult.failure("")
        return self.assign(dialogo.teacher)

    def assign(self, teacher: str) -> EditResult:
        """Pone a ese profesor a cubrir la clase seleccionada."""
        fila = self.current_row()
        if fila is None:
            return EditResult.failure(self.tr("Elige una clase del parte del día"))
        facade, sesion, dia = self.facade, self.bridge.session, self.date
        resultado = self.bridge.edit(
            lambda: facade.assign_substitute(sesion, dia, fila.period, fila.lesson, teacher)
        )
        self.refresh()
        return resultado

    def cancel_lesson(self) -> EditResult:
        """Marca la clase seleccionada como suprimida."""
        fila = self.current_row()
        if fila is None:
            return EditResult.failure(self.tr("Elige una clase del parte del día"))
        facade, sesion, dia = self.facade, self.bridge.session, self.date
        resultado = self.bridge.edit(
            lambda: facade.cancel_lesson(sesion, dia, fila.period, fila.lesson)
        )
        self.refresh()
        return resultado

    def change_room(self, room: str) -> EditResult:
        """Cambia el aula de la clase seleccionada."""
        fila = self.current_row()
        if fila is None:
            return EditResult.failure(self.tr("Elige una clase del parte del día"))
        facade, sesion, dia = self.facade, self.bridge.session, self.date
        resultado = self.bridge.edit(
            lambda: facade.change_room(sesion, dia, fila.period, fila.lesson, room)
        )
        self.refresh()
        return resultado

    def change_room_dialog(self) -> EditResult:
        """Pregunta el aula nueva y la aplica."""
        if self.current_row() is None:
            return EditResult.failure(self.tr("Elige una clase del parte del día"))
        aulas = entity_ids(self.bridge, MasterKind.ROOMS)
        if not aulas:
            return EditResult.failure(self.tr("El proyecto no tiene aulas"))
        dialogo = _RoomDialog(aulas, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted or not dialogo.room:
            return EditResult.failure("")
        return self.change_room(dialogo.room)

    def clear_decision(self) -> EditResult:
        """Borra la decisión de la clase seleccionada."""
        fila = self.current_row()
        if fila is None:
            return EditResult.failure(self.tr("Elige una clase del parte del día"))
        facade, sesion, dia = self.facade, self.bridge.session, self.date
        resultado = self.bridge.edit(
            lambda: facade.clear_decision(sesion, dia, fila.period, fila.lesson)
        )
        self.refresh()
        return resultado

    # --- idioma -------------------------------------------------------------------- #

    def _retranslate(self) -> None:
        self.date_label.setText(self.tr("Día:"))
        self.date_edit.setToolTip(self.tr("Día del que se hace el parte de sustituciones"))
        self.prev_button.setText(self.tr("Día anterior"))
        self.prev_button.setToolTip(self.tr("Ver el parte del día anterior"))
        self.next_button.setText(self.tr("Día siguiente"))
        self.next_button.setToolTip(self.tr("Ver el parte del día siguiente"))
        self._update_holiday_button()
        self.absence_box.setTitle(self.tr("Ausencias del día"))
        self.absence_table.setHorizontalHeaderLabels(
            [
                self.tr("Quién"),
                self.tr("Tipo"),
                self.tr("Desde"),
                self.tr("Hasta"),
                self.tr("Motivo"),
            ]
        )
        self.add_absence_button.setText(self.tr("Añadir"))
        self.add_absence_button.setToolTip(
            self.tr("Da de alta la falta de un profesor, una clase o un aula")
        )
        self.remove_absence_button.setText(self.tr("Quitar"))
        self.remove_absence_button.setToolTip(
            self.tr("Borra la ausencia elegida y las decisiones que venían de ella")
        )
        self.day_box.setTitle(self.tr("Clases afectadas"))
        self.day_table.setHorizontalHeaderLabels(
            [
                self.tr("Hora"),
                self.tr("Lección"),
                self.tr("Materia"),
                self.tr("Clases"),
                self.tr("Profesor"),
                self.tr("Aula"),
                self.tr("Decisión"),
                self.tr("Sustituto"),
            ]
        )
        self.propose_button.setText(self.tr("Proponer sustituto"))
        self.propose_button.setToolTip(
            self.tr("Muestra quién puede cubrirla, del mejor al peor, con el motivo del orden")
        )
        self.cancel_button.setText(self.tr("Suprimir"))
        self.cancel_button.setToolTip(self.tr("La clase no se da ese día"))
        self.room_button.setText(self.tr("Cambiar aula"))
        self.room_button.setToolTip(self.tr("Da otra aula a esta clase solo ese día"))
        self.clear_button.setText(self.tr("Quitar decisión"))
        self.clear_button.setToolTip(self.tr("Deja la clase otra vez sin resolver"))
        self.counter_box.setTitle(self.tr("Contadores"))
        self.counter_table.setHorizontalHeaderLabels(
            [self.tr("Profesor"), self.tr("Puntos"), self.tr("Asumidas"), self.tr("Reserva")]
        )
        self.hint.setText(
            self.tr(
                "Elige el día, da de alta quién falta y resuelve cada clase: proponer un "
                "sustituto, suprimirla o cambiarle el aula. Los contadores dicen cuántas "
                "sustituciones lleva cada profesor para repartirlas con justicia."
            )
        )
        self.refresh()


class _RoomDialog(QDialog):
    """Elección del aula nueva para una clase de un día."""

    def __init__(self, rooms: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.combo = QComboBox()
        self.combo.addItems(list(rooms))
        self.label = QLabel()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        formulario = QFormLayout()
        formulario.addRow(self.label, self.combo)
        capa = QVBoxLayout(self)
        capa.addLayout(formulario)
        capa.addWidget(self.buttons)
        self.setWindowTitle(self.tr("Cambiar de aula"))
        self.label.setText(self.tr("Aula nueva:"))
        self.combo.setToolTip(self.tr("Aula en la que se dará la clase ese día"))

    @property
    def room(self) -> str:
        return self.combo.currentText()


register(
    WindowSpec(
        key="substitution",
        title="Sustituciones",
        title_de="Vertretungsplanung",
        tab=RibbonTab.MODULES,
        factory=SubstitutionWindow,
        order=20,
        icon="swap",
        tooltip=(
            "Organiza el día en que falta alguien: quién cubre cada clase, cuál se suprime y "
            "qué aula cambia."
        ),
        tooltip_de=(
            "Organisiert den Tag, an dem jemand fehlt: wer welchen Unterricht übernimmt, was "
            "entfällt und welcher Raum wechselt."
        ),
    )
)
