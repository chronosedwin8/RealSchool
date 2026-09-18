"""Ventana Rejillas de tiempo: crear, copiar, renombrar y editar rejillas (sección 8).

Desde aquí se monta la jornada desde cero, sin otra herramienta:

- Barra de herramientas: Nueva rejilla (diálogo con días, nº de períodos, hora
  de inicio, duración, cambio de clase, recreos y vista previa de las horas),
  Copiar, Renombrar, Borrar, Añadir período, Quitar último período y Generar
  horas (vuelve a calcular las horas de una rejilla sin clases colocadas).
- Casillas de los días lectivos de la rejilla visible.
- Una pestaña por rejilla: tabla período x (Inicio, Fin, Recreo, Mañana/Tarde,
  Minutos) editable en celda, y la lista de clases que la usan. Los recreos
  llevan el icono de descanso y se pintan en gris; una hora rechazada por la
  Fachada queda en rojo con el motivo. Si la Fachada rechaza una orden (p. ej.
  borrar una rejilla en uso), el motivo se ve en una franja roja.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QSignalBlocker, Qt, QTime
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import EditResult, GridView, PeriodRow

from ..icons import icon, icon_size
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import BREAK_COLOR, ERROR_COLOR, day_name
from ..widgets.uikit import Banner, exempt, make_action, set_texts, tool_button

COL_START, COL_END, COL_BREAK, COL_AFTERNOON, COL_MINUTES = range(5)
N_COLUMNS = 5

#: Días que se pueden marcar (1 = lunes ... 7 = domingo).
ALL_DAYS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
#: A partir de esta hora un período cuenta como tarde (igual que la Fachada).
AFTERNOON_FROM = 12 * 60


def _minutes(clock: str) -> int:
    horas, _, minutos = clock.partition(":")
    return int(horas) * 60 + int(minutos)


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def period_length(period: PeriodRow) -> int:
    """Minutos que dura un período."""
    try:
        return max(0, _minutes(period.end) - _minutes(period.start))
    except ValueError:
        return 0


# --------------------------------------------------------------------------- #
# Parámetros y vista previa de una rejilla generada
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class GridParams:
    """Lo que pide el diálogo para generar las horas de una rejilla."""

    name: str
    days: tuple[int, ...]
    periods: int
    start: str
    """`HH:MM`."""
    duration: int
    gap: int
    breaks: dict[int, int] = field(default_factory=dict)
    """`{tras el período lectivo N: minutos de recreo}`."""


@dataclass(frozen=True, slots=True)
class PreviewRow:
    number: int
    start: str
    end: str
    is_break: bool
    afternoon: bool


def preview(params: GridParams) -> tuple[list[PreviewRow], str]:
    """Horas que saldrán con `params` (mismas reglas que la Fachada) y el problema, si lo hay.

    El problema es una clave (`periods`, `duration`, `breaks`, `start`,
    `midnight`); el diálogo la convierte en un texto traducido.
    """
    if params.periods < 1:
        return [], "periods"
    if params.duration < 5:
        return [], "duration"
    if any(k < 1 or k >= params.periods or v < 5 for k, v in params.breaks.items()):
        return [], "breaks"
    try:
        reloj = _minutes(params.start)
    except ValueError:
        return [], "start"
    filas: list[PreviewRow] = []
    numero = 1
    for lectivo in range(1, params.periods + 1):
        filas.append(
            PreviewRow(
                numero,
                _clock(reloj),
                _clock(reloj + params.duration),
                False,
                reloj >= AFTERNOON_FROM,
            )
        )
        reloj += params.duration + params.gap
        numero += 1
        if lectivo in params.breaks:
            minutos = params.breaks[lectivo]
            filas.append(
                PreviewRow(
                    numero, _clock(reloj), _clock(reloj + minutos), True, reloj >= AFTERNOON_FROM
                )
            )
            reloj += minutos + params.gap
            numero += 1
    if _minutes(filas[-1].end) > 24 * 60:
        return filas, "midnight"
    return filas, ""


def params_of(grid: GridView) -> GridParams:
    """Parámetros que reproducen (aproximadamente) una rejilla existente."""
    lectivos = [p for p in grid.periods if not p.is_break]
    primero = lectivos[0] if lectivos else None
    duracion = period_length(primero) if primero is not None else 45
    cambio = 5
    if len(grid.periods) >= 2:
        try:
            cambio = max(0, _minutes(grid.periods[1].start) - _minutes(grid.periods[0].end))
        except ValueError:
            cambio = 5
    recreos: dict[int, int] = {}
    vistos = 0
    for p in grid.periods:
        if p.is_break:
            if 1 <= vistos < len(lectivos):
                recreos[vistos] = max(5, period_length(p))
        else:
            vistos += 1
    return GridParams(
        name=grid.id,
        days=grid.days,
        periods=max(1, len(lectivos)),
        start=grid.periods[0].start if grid.periods else "08:00",
        duration=max(5, duracion or 45),
        gap=cambio,
        breaks=recreos,
    )


# --------------------------------------------------------------------------- #
# Diálogo Nueva rejilla / Generar horas
# --------------------------------------------------------------------------- #


class BreakRow(QWidget):
    """Un recreo: "tras el período N, M minutos" y un botón para quitarlo."""

    def __init__(self, dialog: GridDialog, after: int, minutes: int) -> None:
        super().__init__()
        self.dialog = dialog
        self.after = QSpinBox()
        self.after.setRange(1, 30)
        self.after.setValue(after)
        self.minutes = QSpinBox()
        self.minutes.setRange(5, 240)
        self.minutes.setSingleStep(5)
        self.minutes.setValue(minutes)
        self.minutes.setSuffix(" min")
        self.remove_button = tool_button("remove", lambda: dialog.remove_break(self))
        self.remove_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._after_label = QLabel()
        self._minutes_label = QLabel()
        capa = QHBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.addWidget(self._after_label)
        capa.addWidget(self.after)
        capa.addWidget(self._minutes_label)
        capa.addWidget(self.minutes)
        capa.addWidget(self.remove_button)
        capa.addStretch(1)
        self.after.valueChanged.connect(lambda _v: dialog.update_preview())
        self.minutes.valueChanged.connect(lambda _v: dialog.update_preview())
        self.retranslate()

    def retranslate(self) -> None:
        self._after_label.setText(self.tr("Recreo tras el período"))
        self._minutes_label.setText(self.tr("minutos de recreo:"))
        self.after.setToolTip(self.tr("Número del período lectivo tras el que va el recreo"))
        self.minutes.setToolTip(self.tr("Minutos que dura el recreo"))
        set_texts(self.remove_button, self.tr("Quitar"), self.tr("Quita este recreo"))


class GridDialog(QDialog):
    """Datos para generar las horas de una rejilla, con vista previa en vivo.

    `regenerate=True` es el modo Generar horas: el nombre y los días no se
    editan (la rejilla ya existe).
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        regenerate: bool = False,
        initial: GridParams | None = None,
        language: str = "es",
    ) -> None:
        super().__init__(parent)
        self.regenerate = regenerate
        self.language = language
        base = initial or GridParams(
            name="", days=(1, 2, 3, 4, 5), periods=6, start="08:00", duration=45, gap=5
        )
        self.setWindowIcon(icon("time_grids" if regenerate else "grid_add"))

        self.name_edit = QLineEdit(base.name)
        self.name_edit.setReadOnly(regenerate)
        self.day_checks: dict[int, QCheckBox] = {}
        dias = QHBoxLayout()
        for d in ALL_DAYS:
            casilla = QCheckBox(day_name(d, language)[:3])
            casilla.setChecked(d in base.days)
            casilla.setEnabled(not regenerate)
            casilla.toggled.connect(lambda _v: self.update_preview())
            exempt(casilla, "el texto es el día")
            self.day_checks[d] = casilla
            dias.addWidget(casilla)
        dias.addStretch(1)
        self.periods = QSpinBox()
        self.periods.setRange(1, 30)
        self.periods.setValue(base.periods)
        self.start = QTimeEdit()
        self.start.setDisplayFormat("HH:mm")
        self.start.setTime(QTime.fromString(base.start, "HH:mm"))
        self.duration = QSpinBox()
        self.duration.setRange(5, 240)
        self.duration.setSingleStep(5)
        self.duration.setSuffix(" min")
        self.duration.setValue(base.duration)
        self.gap = QSpinBox()
        self.gap.setRange(0, 60)
        self.gap.setSuffix(" min")
        self.gap.setValue(base.gap)
        for control in (self.periods, self.duration, self.gap):
            control.valueChanged.connect(lambda _v: self.update_preview())
        self.start.timeChanged.connect(lambda _t: self.update_preview())
        self.name_edit.textChanged.connect(lambda _t: self.update_preview())

        self.form = QFormLayout()
        self._labels = [QLabel() for _ in range(6)]
        self.form.addRow(self._labels[0], self.name_edit)
        self.form.addRow(self._labels[1], dias)
        self.form.addRow(self._labels[2], self.periods)
        self.form.addRow(self._labels[3], self.start)
        self.form.addRow(self._labels[4], self.duration)
        self.form.addRow(self._labels[5], self.gap)

        self.breaks_box = QGroupBox()
        self._breaks_layout = QVBoxLayout(self.breaks_box)
        self.break_rows: list[BreakRow] = []
        self.add_break_button = tool_button("break", lambda: self.add_break())
        self._breaks_layout.addWidget(self.add_break_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.preview_box = QGroupBox()
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.verticalHeader().setDefaultSectionSize(22)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.preview_table.setMinimumWidth(260)
        QVBoxLayout(self.preview_box).addWidget(self.preview_table)

        self.error = Banner("error")
        self.error.hide()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setIcon(icon("ok"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setIcon(icon("unplace"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        izquierda = QVBoxLayout()
        izquierda.addLayout(self.form)
        izquierda.addWidget(self.breaks_box)
        izquierda.addStretch(1)
        cuerpo = QHBoxLayout()
        cuerpo.addLayout(izquierda, 3)
        cuerpo.addWidget(self.preview_box, 2)
        raiz = QVBoxLayout(self)
        raiz.addLayout(cuerpo, 1)
        raiz.addWidget(self.error)
        raiz.addWidget(self.buttons)

        self.retranslate()
        for tras, minutos in sorted(base.breaks.items()):
            self.add_break(tras, minutos)
        self.update_preview()
        self.resize(760, 480)

    # --- recreos -------------------------------------------------------------- #

    def add_break(self, after: int | None = None, minutes: int = 20) -> BreakRow:
        """Añade un recreo (por defecto, tras el período del medio)."""
        tras = after if after is not None else max(1, self.periods.value() // 2)
        fila = BreakRow(self, tras, minutes)
        self.break_rows.append(fila)
        self._breaks_layout.insertWidget(self._breaks_layout.count() - 1, fila)
        self.update_preview()
        return fila

    def remove_break(self, row: BreakRow) -> None:
        if row in self.break_rows:
            self.break_rows.remove(row)
            self._breaks_layout.removeWidget(row)
            row.deleteLater()
            self.update_preview()

    def set_breaks(self, breaks: dict[int, int]) -> None:
        for fila in list(self.break_rows):
            self.remove_break(fila)
        for tras, minutos in sorted(breaks.items()):
            self.add_break(tras, minutos)

    # --- valores ----------------------------------------------------------------- #

    def values(self) -> GridParams:
        return GridParams(
            name=self.name_edit.text().strip(),
            days=tuple(d for d, c in self.day_checks.items() if c.isChecked()),
            periods=self.periods.value(),
            start=self.start.time().toString("HH:mm"),
            duration=self.duration.value(),
            gap=self.gap.value(),
            breaks={f.after.value(): f.minutes.value() for f in self.break_rows},
        )

    def problem(self) -> str:
        """Motivo por el que aún no se puede aceptar ("" si todo está bien)."""
        valores = self.values()
        if not valores.name:
            return self.tr("Escribe un nombre para la rejilla")
        if not valores.days:
            return self.tr("Marca al menos un día lectivo")
        if len({f.after.value() for f in self.break_rows}) != len(self.break_rows):
            return self.tr("Hay dos recreos tras el mismo período")
        _filas, clave = preview(valores)
        problemas = {
            "periods": self.tr("La rejilla necesita al menos un período"),
            "duration": self.tr("Un período dura al menos 5 minutos"),
            "breaks": self.tr(
                "Cada recreo va entre dos períodos (tras el 1.º y antes del último) "
                "y dura al menos 5 minutos"
            ),
            "start": self.tr("La hora de inicio no es válida"),
            "midnight": self.tr("La jornada termina después de medianoche"),
        }
        return problemas.get(clave, clave)

    def update_preview(self) -> None:
        filas, _error = preview(self.values())
        tabla = self.preview_table
        tabla.setRowCount(len(filas))
        for i, f in enumerate(filas):
            numero = QTableWidgetItem(str(f.number))
            horas = QTableWidgetItem(f"{f.start} - {f.end}")
            if f.is_break:
                tipo = QTableWidgetItem(icon("break"), self.tr("Recreo"))
            elif f.afternoon:
                tipo = QTableWidgetItem(icon("afternoon"), self.tr("Tarde"))
            else:
                tipo = QTableWidgetItem(icon("morning"), self.tr("Mañana"))
            for col, item in enumerate((numero, horas, tipo)):
                if f.is_break:
                    item.setBackground(QColor(BREAK_COLOR))
                tabla.setItem(i, col, item)
        motivo = self.problem()
        self.error.show_message(motivo)
        boton = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        boton.setEnabled(not motivo)
        boton.setToolTip(motivo)

    def retranslate(self) -> None:
        self.setWindowTitle(
            self.tr("Generar horas") if self.regenerate else self.tr("Nueva rejilla")
        )
        textos = (
            self.tr("Nombre"),
            self.tr("Días lectivos"),
            self.tr("Períodos de clase"),
            self.tr("Primera clase empieza a las"),
            self.tr("Duración de cada período"),
            self.tr("Cambio de clase"),
        )
        for etiqueta, texto in zip(self._labels, textos, strict=True):
            etiqueta.setText(texto)
        self.name_edit.setPlaceholderText(self.tr("p. ej. Primaria, Tarde, Bachillerato"))
        self.name_edit.setToolTip(
            self.tr("Nombre corto de la rejilla; las clases la eligen por este nombre")
        )
        self.periods.setToolTip(
            self.tr("Cuántos períodos de clase hay al día (sin contar recreos)")
        )
        self.start.setToolTip(self.tr("Hora a la que empieza el primer período"))
        self.duration.setToolTip(self.tr("Minutos que dura cada período de clase"))
        self.gap.setToolTip(
            self.tr("Minutos entre el final de un período y el inicio del siguiente")
        )
        self.breaks_box.setTitle(self.tr("Recreos"))
        set_texts(
            self.add_break_button,
            self.tr("Añadir recreo"),
            self.tr("Añade un recreo entre dos períodos (se puede cambiar dónde y cuánto dura)"),
        )
        self.preview_box.setTitle(self.tr("Vista previa de las horas"))
        self.preview_table.setHorizontalHeaderLabels(
            [self.tr("Nº"), self.tr("Horario"), self.tr("Tipo")]
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            self.tr("Generar") if self.regenerate else self.tr("Crear rejilla")
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.tr("Cancelar"))
        for fila in self.break_rows:
            fila.retranslate()


# --------------------------------------------------------------------------- #
# Página de una rejilla
# --------------------------------------------------------------------------- #


class GridPage(QWidget):
    """Una rejilla: tabla de períodos y clases que la usan."""

    def __init__(self, bridge: FacadeBridge, grid: GridView) -> None:
        super().__init__()
        self.bridge = bridge
        self.grid = grid
        self._errors: dict[tuple[int, int], str] = {}
        self._loading = False

        self.table = QTableWidget(0, N_COLUMNS)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setDefaultSectionSize(24)
        cabecera = self.table.horizontalHeader()
        cabecera.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.classes_label = QLabel()
        self.classes = QListWidget()
        self.classes.setMaximumWidth(200)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #4b5563;")

        lateral = QVBoxLayout()
        lateral.addWidget(self.classes_label)
        lateral.addWidget(self.classes, 1)
        centro = QVBoxLayout()
        centro.addWidget(self.table, 1)
        centro.addWidget(self.hint)
        raiz = QHBoxLayout(self)
        raiz.addLayout(centro, 1)
        raiz.addLayout(lateral)
        self.retranslate()
        self.set_grid(grid)

    def set_grid(self, grid: GridView) -> None:
        self.grid = grid
        self._loading = True
        try:
            self.table.setRowCount(len(grid.periods))
            for fila, p in enumerate(grid.periods):
                cabecera = QTableWidgetItem(str(p.number))
                if p.is_break:
                    cabecera.setIcon(icon("break"))
                self.table.setVerticalHeaderItem(fila, cabecera)
                for col, texto in ((COL_START, p.start), (COL_END, p.end)):
                    self.table.setItem(fila, col, QTableWidgetItem(texto))
                for col, marcado in ((COL_BREAK, p.is_break), (COL_AFTERNOON, p.afternoon)):
                    item = QTableWidgetItem()
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked
                    )
                    self.table.setItem(fila, col, item)
                minutos = QTableWidgetItem(f"{period_length(p)} min")
                minutos.setFlags(Qt.ItemFlag.ItemIsEnabled)
                minutos.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.table.setItem(fila, COL_MINUTES, minutos)
                self._paint_row(fila)
            self.classes.clear()
            self.classes.addItems(list(grid.classes))
            self.classes_label.setText(
                self.tr("Clases con esta rejilla ({0})").format(len(grid.classes))
            )
        finally:
            self._loading = False

    def _paint_row(self, row: int) -> None:
        periodo = self.grid.periods[row]
        for col in range(N_COLUMNS):
            item = self.table.item(row, col)
            if item is None:
                continue
            error = self._errors.get((periodo.number, col), "")
            if error:
                item.setBackground(QColor(ERROR_COLOR))
            elif periodo.is_break:
                item.setBackground(QColor(BREAK_COLOR))
            else:
                item.setBackground(QColor("#ffffff"))
            if col == COL_BREAK:
                item.setIcon(icon("break") if periodo.is_break else QIcon())
                item.setText(self.tr("Recreo") if periodo.is_break else "")
            elif col == COL_AFTERNOON:
                item.setIcon(icon("afternoon") if periodo.afternoon else icon("morning"))
                item.setText(self.tr("Tarde") if periodo.afternoon else self.tr("Mañana"))
            item.setToolTip(error or self._cell_help(col))

    def _cell_help(self, column: int) -> str:
        ayudas = {
            COL_START: self.tr("Hora de inicio (HH:MM); escribe para cambiarla"),
            COL_END: self.tr("Hora de fin (HH:MM); escribe para cambiarla"),
            COL_BREAK: self.tr("Marcado: es un recreo, ahí no se colocan clases"),
            COL_AFTERNOON: self.tr(
                "Marcado: el período cuenta como tarde (sol = mañana, luna = tarde)"
            ),
            COL_MINUTES: self.tr("Duración del período en minutos"),
        }
        return ayudas.get(column, "")

    def row_of(self, number: int) -> int:
        return next((i for i, p in enumerate(self.grid.periods) if p.number == number), -1)

    def error_at(self, number: int, column: int) -> str:
        return self._errors.get((number, column), "")

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        fila, col = item.row(), item.column()
        if not 0 <= fila < len(self.grid.periods):
            return
        periodo = self.grid.periods[fila]
        numero = periodo.number
        marcado = item.checkState() == Qt.CheckState.Checked
        if col == COL_START:
            self.edit_period(numero, col, start=item.text().strip())
        elif col == COL_END:
            self.edit_period(numero, col, end=item.text().strip())
        elif col == COL_BREAK and marcado != periodo.is_break:
            self.edit_period(numero, col, is_break=marcado)
        elif col == COL_AFTERNOON and marcado != periodo.afternoon:
            self.edit_period(numero, col, afternoon=marcado)

    def edit_period(
        self,
        number: int,
        column: int,
        *,
        start: str | None = None,
        end: str | None = None,
        is_break: bool | None = None,
        afternoon: bool | None = None,
    ) -> EditResult:
        """Edita un período; si la Fachada lo rechaza, la celda queda en rojo."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        svc, grid_id = self.bridge.service, self.grid.id
        if start == "" or end == "":
            resultado = EditResult.failure(self.tr("Indica una hora HH:MM"))
        else:
            resultado = self.bridge.edit(
                lambda: svc.set_period(
                    self.bridge.session,
                    grid_id,
                    number,
                    start=start,
                    end=end,
                    is_break=is_break,
                    afternoon=afternoon,
                )
            )
        if resultado.ok:
            self._errors.pop((number, column), None)
        else:
            self._errors[(number, column)] = resultado.message
            self.bridge.status.emit(resultado.message)
        fila = self.row_of(number)
        if fila >= 0:
            self._loading = True
            try:
                self._paint_row(fila)
            finally:
                self._loading = False
        return resultado

    def retranslate(self) -> None:
        titulos = (
            self.tr("Inicio"),
            self.tr("Fin"),
            self.tr("Recreo"),
            self.tr("Mañana / tarde"),
            self.tr("Minutos"),
        )
        for col, titulo in enumerate(titulos):
            cabecera = QTableWidgetItem(titulo)
            cabecera.setToolTip(self._cell_help(col))
            self.table.setHorizontalHeaderItem(col, cabecera)
        self.classes_label.setText(
            self.tr("Clases con esta rejilla ({0})").format(len(self.grid.classes))
        )
        self.classes.setToolTip(
            self.tr("Clases que usan esta rejilla; se cambia en la columna Rejilla de Clases")
        )
        self.hint.setText(
            self.tr(
                "Escribe las horas directamente en la tabla. Para quitar un período "
                "intermedio, márcalo como recreo; solo se puede quitar el último."
            )
        )
        if self.table.rowCount():
            self._loading = True
            try:
                for fila in range(self.table.rowCount()):
                    self._paint_row(fila)
            finally:
                self._loading = False


# --------------------------------------------------------------------------- #
# Ventana
# --------------------------------------------------------------------------- #


class TimeGridsWindow(QWidget):
    """Rejillas de tiempo del proyecto, una pestaña por rejilla, con su barra de órdenes."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.pages: dict[str, GridPage] = {}

        self.toolbar = QToolBar()
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar.setIconSize(icon_size("button"))
        self.new_action = make_action(self, "grid_add", self.new_grid_dialog)
        self.copy_action = make_action(self, "copy", self.copy_dialog)
        self.rename_action = make_action(self, "rename", self.rename_dialog)
        self.delete_action = make_action(self, "grid_remove", self.delete_dialog)
        self.add_period_action = make_action(self, "period_add", self.add_period)
        self.remove_period_action = make_action(self, "remove", self.remove_last_period)
        self.regenerate_action = make_action(self, "wizard", self.regenerate_dialog)
        for accion in (self.new_action, self.copy_action, self.rename_action, self.delete_action):
            self.toolbar.addAction(accion)
        self.toolbar.addSeparator()
        for accion in (self.add_period_action, self.remove_period_action, self.regenerate_action):
            self.toolbar.addAction(accion)

        self.days_label = QLabel()
        self.day_checks: dict[int, QCheckBox] = {}
        dias = QHBoxLayout()
        dias.addWidget(self.days_label)
        for d in ALL_DAYS:
            casilla = QCheckBox()
            casilla.toggled.connect(lambda _v: self._on_day_toggled())
            exempt(casilla, "el texto es el día")
            self.day_checks[d] = casilla
            dias.addWidget(casilla)
        dias.addStretch(1)

        self.message = Banner("error")
        self.message.hide()
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(lambda _i: self._update_state())
        self.empty = Banner("tip")

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)
        raiz.addWidget(self.toolbar)
        raiz.addLayout(dias)
        raiz.addWidget(self.message)
        raiz.addWidget(self.empty)
        raiz.addWidget(self.tabs, 1)

        bridge.refreshed.connect(self.refresh)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()
        self.refresh()

    # --- carga -------------------------------------------------------------------- #

    def grids(self) -> tuple[GridView, ...]:
        return self.bridge.service.grids(self.bridge.session) if self.bridge.has_session else ()

    def refresh(self) -> None:
        grids = self.grids()
        if tuple(self.pages) == tuple(g.id for g in grids):
            for i, g in enumerate(grids):
                self.pages[g.id].set_grid(g)
                self.tabs.setTabText(i, g.name)
        else:
            actual = self.current_grid_id()
            with QSignalBlocker(self.tabs):
                self.tabs.clear()
                for page in self.pages.values():
                    page.deleteLater()
                self.pages = {}
                for g in grids:
                    page = GridPage(self.bridge, g)
                    self.pages[g.id] = page
                    self.tabs.addTab(page, icon("time_grids"), g.name)
                ids = [g.id for g in grids]
                if actual in ids:
                    self.tabs.setCurrentIndex(ids.index(actual))
        self._update_state()

    def page(self, grid_id: str) -> GridPage:
        return self.pages[grid_id]

    def current_grid_id(self) -> str | None:
        page = self.tabs.currentWidget()
        return page.grid.id if isinstance(page, GridPage) else None

    def current_grid(self) -> GridView | None:
        page = self.tabs.currentWidget()
        return page.grid if isinstance(page, GridPage) else None

    def select_grid(self, grid_id: str) -> bool:
        page = self.pages.get(grid_id)
        if page is None:
            return False
        self.tabs.setCurrentWidget(page)
        return True

    def _update_state(self) -> None:
        abierto = self.bridge.has_session
        grid = self.current_grid()
        self.new_action.setEnabled(abierto)
        for accion in (
            self.copy_action,
            self.rename_action,
            self.delete_action,
            self.add_period_action,
            self.remove_period_action,
            self.regenerate_action,
        ):
            accion.setEnabled(abierto and grid is not None)
        for d, casilla in self.day_checks.items():
            with QSignalBlocker(casilla):
                casilla.setChecked(grid is not None and d in grid.days)
            casilla.setEnabled(grid is not None)
        if not abierto:
            self.empty.show_message(self.tr("Abre o crea un proyecto para ver sus rejillas."))
        elif not self.pages:
            self.empty.show_message(
                self.tr(
                    "El proyecto no tiene rejillas de tiempo. Pulsa «Nueva rejilla» para "
                    "crear la jornada: días, períodos, horas y recreos."
                )
            )
        else:
            self.empty.hide()

    # --- órdenes (métodos públicos, sin diálogos) ------------------------------------ #

    def _apply(self, action: EditResult | None, *, select: str | None = None) -> EditResult:
        resultado = action if action is not None else EditResult.failure(self.tr("Sin cambios"))
        self.show_message("" if resultado.ok else resultado.message)
        self.refresh()
        if select is not None and resultado.ok:
            self.select_grid(select)
        return resultado

    def _no_grid(self) -> EditResult:
        return self._apply(EditResult.failure(self.tr("Elige primero una rejilla")))

    def create_grid(self, params: GridParams) -> EditResult:
        """Crea una rejilla con horas generadas y la muestra."""
        if not self.bridge.has_session:
            return self._apply(EditResult.failure(self.tr("No hay proyecto abierto")))
        svc = self.bridge.service
        resultado = self.bridge.edit(
            lambda: svc.add_grid(
                self.bridge.session,
                params.name,
                days=params.days,
                periods=params.periods,
                start=params.start,
                duration=params.duration,
                gap=params.gap,
                breaks=dict(params.breaks),
            )
        )
        return self._apply(resultado, select=params.name.strip())

    def copy_grid(self, new_id: str) -> EditResult:
        """Duplica la rejilla visible con otro nombre."""
        origen = self.current_grid_id()
        if origen is None:
            return self._no_grid()
        svc = self.bridge.service
        resultado = self.bridge.edit(lambda: svc.copy_grid(self.bridge.session, origen, new_id))
        return self._apply(resultado, select=new_id.strip())

    def rename_grid(self, name: str) -> EditResult:
        """Nombre largo de la rejilla visible (el nombre corto no cambia)."""
        grid_id = self.current_grid_id()
        if grid_id is None:
            return self._no_grid()
        svc = self.bridge.service
        resultado = self.bridge.edit(lambda: svc.rename_grid(self.bridge.session, grid_id, name))
        return self._apply(resultado, select=grid_id)

    def delete_grid(self) -> EditResult:
        """Borra la rejilla visible; si está en uso, la franja roja explica por qué no."""
        grid_id = self.current_grid_id()
        if grid_id is None:
            return self._no_grid()
        svc = self.bridge.service
        return self._apply(self.bridge.edit(lambda: svc.remove_grid(self.bridge.session, grid_id)))

    def add_period(self) -> EditResult:
        """Añade un período al final, con la duración y el cambio de los anteriores."""
        grid = self.current_grid()
        if grid is None:
            return self._no_grid()
        lectivos = [p for p in grid.periods if not p.is_break]
        duracion = period_length(lectivos[-1]) if lectivos else 45
        cambio = 5
        if len(grid.periods) >= 2:
            try:
                cambio = max(0, _minutes(grid.periods[-1].start) - _minutes(grid.periods[-2].end))
            except ValueError:
                cambio = 5
        svc, grid_id = self.bridge.service, grid.id
        resultado = self.bridge.edit(
            lambda: svc.add_period(
                self.bridge.session, grid_id, duration=max(5, duracion or 45), gap=cambio
            )
        )
        return self._apply(resultado, select=grid_id)

    def remove_last_period(self) -> EditResult:
        """Quita el último período (la Fachada lo impide si hay clases colocadas)."""
        grid = self.current_grid()
        if grid is None or not grid.periods:
            return self._no_grid()
        ultimo = max(p.number for p in grid.periods)
        svc, grid_id = self.bridge.service, grid.id
        resultado = self.bridge.edit(
            lambda: svc.remove_period(self.bridge.session, grid_id, ultimo)
        )
        return self._apply(resultado, select=grid_id)

    def set_days(self, days: tuple[int, ...]) -> EditResult:
        """Días lectivos de la rejilla visible."""
        grid_id = self.current_grid_id()
        if grid_id is None:
            return self._no_grid()
        svc = self.bridge.service
        resultado = self.bridge.edit(lambda: svc.set_grid_days(self.bridge.session, grid_id, days))
        return self._apply(resultado, select=grid_id)

    def regenerate(self, params: GridParams) -> EditResult:
        """Vuelve a generar las horas de la rejilla visible."""
        grid_id = self.current_grid_id()
        if grid_id is None:
            return self._no_grid()
        svc = self.bridge.service
        resultado = self.bridge.edit(
            lambda: svc.regenerate_grid(
                self.bridge.session,
                grid_id,
                periods=params.periods,
                start=params.start,
                duration=params.duration,
                gap=params.gap,
                breaks=dict(params.breaks),
            )
        )
        return self._apply(resultado, select=grid_id)

    def show_message(self, text: str) -> None:
        self.message.show_message(text, "error")
        if text:
            self.bridge.status.emit(text)

    def _on_day_toggled(self) -> None:
        dias = tuple(d for d, c in self.day_checks.items() if c.isChecked())
        self.set_days(dias)

    # --- diálogos (envoltorios de las órdenes; las pruebas los sustituyen) ------------- #

    def exec_dialog(self, dialog: QDialog) -> bool:
        return dialog.exec() == QDialog.DialogCode.Accepted

    def ask_text(self, title: str, label: str, default: str = "") -> str | None:
        texto, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Normal, default)
        return texto if ok else None

    def confirm(self, title: str, text: str) -> bool:
        respuesta = QMessageBox.question(self, title, text)
        return respuesta == QMessageBox.StandardButton.Yes

    def make_dialog(self, *, regenerate: bool = False) -> GridDialog:
        grid = self.current_grid()
        inicial = params_of(grid) if regenerate and grid is not None else None
        if inicial is None:
            existentes = {g.id for g in self.grids()}
            nombre = next(
                (f"Rejilla {n}" for n in range(1, 100) if f"Rejilla {n}" not in existentes), ""
            )
            inicial = GridParams(
                name=nombre,
                days=(1, 2, 3, 4, 5),
                periods=6,
                start="08:00",
                duration=45,
                gap=5,
                breaks={3: 20},
            )
        return GridDialog(
            self, regenerate=regenerate, initial=inicial, language=self.bridge.language
        )

    def new_grid_dialog(self) -> EditResult | None:
        dialogo = self.make_dialog()
        if not self.exec_dialog(dialogo):
            return None
        return self.create_grid(dialogo.values())

    def regenerate_dialog(self) -> EditResult | None:
        if self.current_grid() is None:
            return None
        dialogo = self.make_dialog(regenerate=True)
        if not self.exec_dialog(dialogo):
            return None
        return self.regenerate(dialogo.values())

    def copy_dialog(self) -> EditResult | None:
        origen = self.current_grid_id()
        if origen is None:
            return None
        nombre = self.ask_text(
            self.tr("Copiar rejilla"),
            self.tr("Nombre corto de la copia de «{0}»:").format(origen),
            self.tr("{0} (copia)").format(origen),
        )
        return self.copy_grid(nombre) if nombre else None

    def rename_dialog(self) -> EditResult | None:
        grid = self.current_grid()
        if grid is None:
            return None
        nombre = self.ask_text(
            self.tr("Renombrar rejilla"),
            self.tr("Nombre completo de «{0}» (el nombre corto no cambia):").format(grid.id),
            grid.name,
        )
        return self.rename_grid(nombre) if nombre is not None else None

    def delete_dialog(self) -> EditResult | None:
        grid_id = self.current_grid_id()
        if grid_id is None:
            return None
        if not self.confirm(
            self.tr("Borrar rejilla"),
            self.tr("¿Borrar la rejilla «{0}»? Se puede deshacer.").format(grid_id),
        ):
            return None
        return self.delete_grid()

    # --- idioma --------------------------------------------------------------------- #

    def _retranslate(self) -> None:
        set_texts(
            self.new_action,
            self.tr("Nueva rejilla"),
            self.tr("Crea una rejilla nueva: días, períodos, horas de inicio y recreos"),
        )
        set_texts(
            self.copy_action,
            self.tr("Copiar"),
            self.tr("Duplica la rejilla visible para hacer otra con horas parecidas"),
        )
        set_texts(
            self.rename_action,
            self.tr("Renombrar"),
            self.tr("Cambia el nombre completo de la rejilla visible"),
        )
        set_texts(
            self.delete_action,
            self.tr("Borrar"),
            self.tr("Borra la rejilla visible (solo si ninguna clase ni lección la usa)"),
        )
        set_texts(
            self.add_period_action,
            self.tr("Añadir período"),
            self.tr("Añade un período al final de la jornada, con la misma duración"),
        )
        set_texts(
            self.remove_period_action,
            self.tr("Quitar último período"),
            self.tr("Quita el último período de la jornada (si no tiene clases colocadas)"),
        )
        set_texts(
            self.regenerate_action,
            self.tr("Generar horas"),
            self.tr("Vuelve a calcular todas las horas a partir de inicio, duración y recreos"),
        )
        self.days_label.setText(self.tr("Días lectivos:"))
        for d, casilla in self.day_checks.items():
            casilla.setText(day_name(d, self.bridge.language))
            casilla.setToolTip(
                self.tr("Marcado: hay clase el {0} en esta rejilla").format(
                    # En alemán los días van con mayúscula.
                    day_name(d, "es").lower()
                    if self.bridge.language == "es"
                    else day_name(d, self.bridge.language)
                )
            )
        for page in self.pages.values():
            page.retranslate()
        self._update_state()


register(
    WindowSpec(
        key="time_grids",
        title="Rejillas de tiempo",
        title_de="Zeitraster",
        tab=RibbonTab.MASTER_DATA,
        factory=TimeGridsWindow,
        order=7,
        icon="time_grids",
        tooltip="Define la jornada: días lectivos, períodos, horas y recreos de cada rejilla.",
        tooltip_de=(
            "Legt den Schultag fest: Unterrichtstage, Stunden, Uhrzeiten und Pausen jedes "
            "Zeitrasters."
        ),
    )
)
