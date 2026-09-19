"""Ventana Sustituciones: el parte del día cuando falta alguien.

El horario es de la semana; esta ventana trabaja sobre un **día concreto**. Se
elige la fecha y se ve, de un vistazo:

- las **ausencias** vigentes ese día (profesores, clases o aulas), con alta y baja;
- las **clases afectadas** por esas ausencias y las decisiones ya tomadas;
- los **contadores** de sustituciones de cada profesor, para repartir con justicia.

A la derecha hay un panel permanente de **profesores disponibles** (como el
"Propuesta -> Sustitución" de Untis): al elegir una clase afectada se llena con
los profesores que podrían cubrirla, de mejor a peor, cada uno con la razón de
su puesto (ya está en el centro, da la materia, cuántas sustituciones lleva...).
Un doble clic, o el botón "Asignar", lo pone de sustituto. En la pestaña de al
lado siguen los contadores. También se puede suprimir la clase o cambiarle el
aula.

Las ausencias se escriben con **horas de reloj**, como en Untis ("desde el
18/09 a las 07:00 hasta el 18/09 a las 17:40"); quien las traduce a números de
hora es la Fachada, que es la que conoce la rejilla de cada entidad.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import EditResult, MasterKind
from scheduling_platform.application.untis.substitution import (
    AbsenceRow,
    AbsenceWindowView,
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

#: Formato de las horas de reloj de una ausencia (`07:00`), igual que en Untis.
CLOCK_FORMAT = "HH:mm"

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


def _day_and_time(date_edit: QDateEdit, at_label: QLabel, time_edit: QTimeEdit) -> QWidget:
    """Fila "el [fecha] a las [HH:MM]" para el formulario de la ausencia."""
    caja = QWidget()
    capa = QHBoxLayout(caja)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.addWidget(date_edit)
    capa.addWidget(at_label)
    capa.addWidget(time_edit)
    capa.addStretch(1)
    return caja


class AbsenceDialog(QDialog):
    """Alta de una ausencia: quién falta, desde qué día y hora hasta cuáles.

    Se escribe como en Untis, con **horas de reloj**: "desde el 18/09 a las
    07:00 hasta el 18/09 a las 17:40". La casilla "Todo el día" viene marcada,
    que es el caso normal; al desmarcarla los relojes se rellenan con el
    principio y el final de la jornada de esa entidad.

    La traducción de reloj a números de hora la hace la Fachada
    (`absence_periods`), que es la que conoce la rejilla; aquí solo se enseña
    en qué se traduce y se pasan los números ya calculados.
    """

    def __init__(self, bridge: FacadeBridge, day: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self.kind_combo = QComboBox()
        for kind in ABSENCE_KINDS:
            self.kind_combo.addItem(icon(KIND_ICONS[kind]), kind, kind)
        self.kind_combo.currentIndexChanged.connect(lambda _i: self._load_entities())
        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(140)
        self.entity_combo.currentIndexChanged.connect(lambda _i: self._update_window())
        fecha = QDate.fromString(day, DATE_FORMAT)
        self.begin = QDateEdit(fecha if fecha.isValid() else QDate.currentDate())
        self.end = QDateEdit(fecha if fecha.isValid() else QDate.currentDate())
        for caja in (self.begin, self.end):
            caja.setCalendarPopup(True)
            caja.setDisplayFormat("dd/MM/yyyy")
            caja.dateChanged.connect(lambda _d: self._update_window())
        self.begin_time = QTimeEdit(QTime(8, 0))
        self.end_time = QTimeEdit(QTime(14, 0))
        for reloj in (self.begin_time, self.end_time):
            reloj.setDisplayFormat(CLOCK_FORMAT)
            reloj.setEnabled(False)
            reloj.timeChanged.connect(lambda _t: self._update_window())
        self.all_day = QCheckBox()
        self.all_day.setChecked(True)
        self.all_day.toggled.connect(self._toggle_all_day)
        self.reason = QLineEdit()
        self.window_label = QLabel()
        self.window_label.setWordWrap(True)

        self.labels: dict[str, QLabel] = {}
        formulario = QFormLayout()
        for clave, campo in (
            ("kind", self.kind_combo),
            ("entity", self.entity_combo),
            ("all_day", self.all_day),
            ("begin", _day_and_time(self.begin, self._at_label("begin_at"), self.begin_time)),
            ("end", _day_and_time(self.end, self._at_label("end_at"), self.end_time)),
            ("reason", self.reason),
            ("window", self.window_label),
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

    def _at_label(self, clave: str) -> QLabel:
        """Etiqueta "a las" entre la fecha y el reloj (se traduce como el resto)."""
        self.labels.setdefault(clave, QLabel())
        return self.labels[clave]

    def _load_entities(self) -> None:
        self.entity_combo.clear()
        self.entity_combo.addItems(list(entity_ids(self.bridge, KIND_MASTER[self.kind])))

    @property
    def facade(self) -> SubstitutionMixin:
        """La Fachada, que traduce las horas de reloj a números de hora."""
        return self.bridge.service

    @property
    def kind(self) -> str:
        return str(self.kind_combo.currentData() or ABSENCE_KINDS[0])

    @property
    def entity(self) -> str:
        return self.entity_combo.currentText()

    @property
    def from_time(self) -> str:
        """Hora de reloj `HH:MM` de inicio (vacía si falta todo el día)."""
        if self.all_day.isChecked():
            return ""
        return str(self.begin_time.time().toString(CLOCK_FORMAT))

    @property
    def to_time(self) -> str:
        """Hora de reloj `HH:MM` de fin (vacía si falta todo el día)."""
        if self.all_day.isChecked():
            return ""
        return str(self.end_time.time().toString(CLOCK_FORMAT))

    def window_view(self, whole_day: bool = False) -> AbsenceWindowView:
        """Traducción del tramo elegido a números de hora (la hace la Fachada).

        Con `whole_day` se pide la jornada entera de la entidad, que es de
        donde salen las horas con las que se rellenan los relojes.
        """
        if not self.bridge.has_session or not self.entity:
            return AbsenceWindowView()
        desde = "" if whole_day else self.from_time
        hasta = "" if whole_day else self.to_time
        return self.facade.absence_periods(
            self.bridge.session, self.kind, self.entity, desde, hasta
        )

    @property
    def error(self) -> str:
        """Por qué no vale el tramo elegido (vacío si vale o es todo el día)."""
        if self.all_day.isChecked():
            return ""
        vista = self.window_view()
        return "" if vista.found else vista.label

    def values(self) -> tuple[str, str, str, str, int | None, int | None, str]:
        """Lo que hay que pasar a la Fachada (las horas, ya como números).

        Todo el día son las dos horas en `None` ("sin límite"), que no es lo
        mismo que la hora 0: un colegio con hora cero la tiene de verdad.
        """
        primera: int | None = None
        ultima: int | None = None
        if not self.all_day.isChecked():
            vista = self.window_view()
            primera, ultima = vista.first, vista.last
        return (
            self.kind,
            self.entity,
            self.begin.date().toString(DATE_FORMAT),
            self.end.date().toString(DATE_FORMAT),
            primera,
            ultima,
            self.reason.text(),
        )

    def _toggle_all_day(self, checked: bool) -> None:
        """Sin "todo el día" se editan las horas, rellenas con la jornada."""
        for reloj in (self.begin_time, self.end_time):
            reloj.setEnabled(not checked)
        if not checked:
            self._fill_day_times()
        self._update_window()

    def _fill_day_times(self) -> None:
        """Pone en los relojes el principio y el final de la jornada."""
        jornada = self.window_view(whole_day=True)
        if not jornada.found:
            return
        relojes = ((self.begin_time, jornada.from_time), (self.end_time, jornada.to_time))
        for reloj, texto in relojes:
            hora = QTime.fromString(texto, CLOCK_FORMAT)
            if not hora.isValid():
                continue
            reloj.blockSignals(True)
            reloj.setTime(hora)
            reloj.blockSignals(False)

    def _update_window(self) -> None:
        """Reescribe la línea que dice en qué horas se traduce la ausencia."""
        self.window_label.setText(self.window_view().label)

    def _retranslate(self) -> None:
        self.setWindowTitle(self.tr("Nueva ausencia"))
        nombres = {
            "teacher": self.tr("Profesor"),
            "class": self.tr("Clase"),
            "room": self.tr("Aula"),
        }
        for i, kind in enumerate(ABSENCE_KINDS):
            self.kind_combo.setItemText(i, nombres[kind])
        self.all_day.setText(self.tr("Todo el día"))
        self.all_day.setToolTip(
            self.tr("Falta la jornada entera; quítale la marca para dar horas de reloj")
        )
        textos = {
            "kind": (self.tr("Falta un:"), self.tr("Qué falta: un profesor, una clase o un aula")),
            "entity": (self.tr("Quién:"), self.tr("El profesor, la clase o el aula que falta")),
            "all_day": (self.tr("Duración:"), self.tr("Toda la jornada o un tramo de horas")),
            "begin": (self.tr("Desde el día:"), self.tr("Primer día de la ausencia")),
            "begin_at": (self.tr("a las"), self.tr("Hora de reloj a la que empieza la ausencia")),
            "end": (self.tr("Hasta el día:"), self.tr("Último día de la ausencia (incluido)")),
            "end_at": (self.tr("a las"), self.tr("Hora de reloj a la que termina la ausencia")),
            "reason": (
                self.tr("Motivo:"),
                self.tr("Por qué falta: enfermedad, curso, excursión..."),
            ),
            "window": (
                self.tr("Se traduce en:"),
                self.tr("Horas de clase que quedan dentro del tramo elegido"),
            ),
        }
        for clave, (texto, ayuda) in textos.items():
            self.labels[clave].setText(texto)
            self.labels[clave].setToolTip(ayuda)
        self._update_window()


class SubstitutionWindow(QWidget):
    """Parte del día: ausencias, clases afectadas, disponibles y contadores.

    La columna de la derecha son dos pestañas: "Disponibles", que sigue a la
    fila elegida en "Clases afectadas" y al día, y "Contadores", la de siempre.
    """

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.report: DayReport | None = None
        self.rows: tuple[DayRow, ...] = ()
        self.absence_rows: tuple[AbsenceRow, ...] = ()
        self.available_rows: tuple[CandidateRow, ...] = ()

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

        self.available_page = QWidget()
        self.available_header = QLabel()
        self.available_header.setWordWrap(True)
        self.available_table = _table(4)
        # Con el colegio real hay más de cien disponibles por hora: la columna
        # larga se estira en vez de medirse fila a fila, que es lo que cuesta.
        cabecera_disp = self.available_table.horizontalHeader()
        cabecera_disp.setStretchLastSection(False)
        cabecera_disp.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # El nombre y los dos contadores ocupan lo justo: el resto es para la
        # explicación, que es lo que hay que leer para decidir.
        for columna in (0, 2, 3):
            cabecera_disp.setSectionResizeMode(columna, QHeaderView.ResizeMode.ResizeToContents)
        self.available_table.doubleClicked.connect(lambda _i: self.assign_selected())
        self.available_empty = EmptyHint(self.available_table)
        self.assign_button = tool_button("activate", self.assign_selected)
        botones_disp = QHBoxLayout()
        botones_disp.addWidget(self.assign_button)
        botones_disp.addStretch(1)
        capa_disp = QVBoxLayout(self.available_page)
        capa_disp.addWidget(self.available_header)
        capa_disp.addWidget(self.available_table, 1)
        capa_disp.addLayout(botones_disp)

        self.counter_page = QWidget()
        self.counter_table = _table(4)
        capa_contadores = QVBoxLayout(self.counter_page)
        capa_contadores.addWidget(self.counter_table, 1)

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.available_page, "")
        self.right_tabs.addTab(self.counter_page, "")

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
        centro.addWidget(self.right_tabs, 4)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)
        raiz.addLayout(barra)
        raiz.addLayout(centro, 1)
        raiz.addWidget(self.hint)

        self.day_table.itemSelectionChanged.connect(self._fill_available)
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
            self._fill_available()
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
        self._fill_available()
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
            self.day_table.setItem(i, 0, _cell(fila.period_label or str(fila.period)))
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

    def _fill_available(self) -> None:
        """Llena el panel de la derecha con quién puede cubrir la clase elegida.

        Es el "Propuesta -> Sustitución" de Untis: siempre visible y siempre
        referido a la fila elegida en "Clases afectadas". Las filas vienen ya
        ordenadas de mejor a peor de la Fachada, así que se pintan tal cual.
        """
        self.available_rows = ()
        self.available_table.setRowCount(0)
        titulo = self.tr("Profesores disponibles")
        if not self.bridge.has_session:
            self._show_available(titulo, self.tr("Sin proyecto: abre o crea uno."))
            return
        fila = self.current_row()
        if fila is None:
            self._show_available(
                titulo, self.tr("Elige una clase afectada para ver quién puede cubrirla.")
            )
            return
        titulo = self.tr("Disponibles para la hora {0}, {1}").format(
            fila.period_label or fila.period, self._lesson_text(fila)
        )
        if fila.decided:
            self._show_available(
                titulo,
                self.tr("Ya está resuelta ({0}). Quita la decisión para volver a elegir.").format(
                    fila.kind_label
                ),
            )
            return
        if not fila.absent_teachers:
            self._show_available(
                titulo, self.tr("Aquí no falta ningún profesor: no hace falta sustituto.")
            )
            return
        filas = self.candidates()
        if not filas:
            self._show_available(titulo, self.tr("Nadie está libre a esa hora."))
            return
        self.available_rows = filas
        self.available_table.setUpdatesEnabled(False)
        self.available_table.setRowCount(len(filas))
        for i, c in enumerate(filas):
            self.available_table.setItem(i, 0, _cell(c.teacher, c.name))
            self.available_table.setItem(i, 1, _cell(c.reason, c.reason))
            self.available_table.setItem(i, 2, _cell(str(c.counter)))
            self.available_table.setItem(i, 3, _cell(str(c.lock)))
        self.available_table.setUpdatesEnabled(True)
        self._show_available(titulo, "")
        self.available_table.selectRow(0)

    def _show_available(self, title: str, hint: str) -> None:
        """Encabezado del panel y, si no hay a quién proponer, por qué."""
        self.available_header.setText(title)
        self.available_empty.show_hint(hint)
        self.assign_button.setEnabled(not hint)

    @staticmethod
    def _lesson_text(fila: DayRow) -> str:
        """Materia y grupos de una clase afectada, p. ej. `COROK9 (K9A, K9B)`."""
        grupos = ", ".join(fila.classes)
        materia = fila.subject or str(fila.lesson)
        return f"{materia} ({grupos})" if grupos else materia

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
        if dialogo.error:
            return EditResult.failure(dialogo.error)
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
        """Atajo: pone al primero del panel de disponibles, que es el mejor."""
        if self.current_row() is None:
            return EditResult.failure(self.tr("Elige una clase del parte del día"))
        if not self.available_rows:
            return EditResult.failure(self.tr("Nadie está libre esa hora"))
        self.available_table.selectRow(0)
        return self.assign(self.available_rows[0].teacher)

    def assign_selected(self) -> EditResult:
        """Pone de sustituto al profesor elegido en el panel de disponibles."""
        i = self.available_table.currentRow()
        if not 0 <= i < len(self.available_rows):
            return EditResult.failure(self.tr("Elige un profesor de la lista de disponibles"))
        return self.assign(self.available_rows[i].teacher)

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
            self.tr("Atajo: pone al primero de la lista de disponibles, que es el mejor")
        )
        self.cancel_button.setText(self.tr("Suprimir"))
        self.cancel_button.setToolTip(self.tr("La clase no se da ese día"))
        self.room_button.setText(self.tr("Cambiar aula"))
        self.room_button.setToolTip(self.tr("Da otra aula a esta clase solo ese día"))
        self.clear_button.setText(self.tr("Quitar decisión"))
        self.clear_button.setToolTip(self.tr("Deja la clase otra vez sin resolver"))
        self.right_tabs.setTabText(0, self.tr("Disponibles"))
        self.right_tabs.setTabToolTip(
            0, self.tr("Quién puede cubrir la clase elegida, del mejor al peor")
        )
        self.right_tabs.setTabText(1, self.tr("Contadores"))
        self.right_tabs.setTabToolTip(
            1, self.tr("Cuántas sustituciones lleva cada profesor en el curso")
        )
        self.available_table.setHorizontalHeaderLabels(
            [
                self.tr("Profesor"),
                self.tr("Por qué"),
                self.tr("Sustituciones"),
                self.tr("Reserva"),
            ]
        )
        self.available_table.setToolTip(
            self.tr(
                "El primero de la lista es el mejor: se prefiere a quien ya está en el centro, "
                "luego a quien da la materia o al grupo, y después a quien menos sustituciones "
                "lleva. Nunca se propone a quien tiene clase o está ausente."
            )
        )
        self.assign_button.setText(self.tr("Asignar"))
        self.assign_button.setToolTip(
            self.tr("Pone al profesor elegido a cubrir la clase (también con doble clic)")
        )
        self.counter_table.setHorizontalHeaderLabels(
            [self.tr("Profesor"), self.tr("Puntos"), self.tr("Asumidas"), self.tr("Reserva")]
        )
        self.hint.setText(
            self.tr(
                "Elige el día, da de alta quién falta y resuelve cada clase: elegir un "
                "sustituto en el panel de la derecha, suprimirla o cambiarle el aula. Los "
                "contadores dicen cuántas sustituciones lleva cada profesor."
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
