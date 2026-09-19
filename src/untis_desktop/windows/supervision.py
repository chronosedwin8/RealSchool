"""Ventana Guardias de recreo (Pausenaufsichten): quién vigila cada recreo.

La parrilla es **zonas x (día, recreo)**, como la de Untis: una fila por zona
que hay que vigilar (patio, pasillos, comedor...) y una columna por recreo de
cada día lectivo de la rejilla. En cada celda, un desplegable con el profesor de
guardia; el turno puesto a mano queda fijado (icono de chincheta) y el reparto
automático lo respeta.

Barra de herramientas: Nueva zona, Renombrar, Borrar, Generar turnos (crea los
turnos vacíos de la rejilla: uno por zona, día y recreo), Repartir guardias
(reparte los que no tienen profesor, equilibrando minutos), Soltar (quita la
chincheta) y Quitar profesor.

A la derecha, el resumen por profesor: minutos de guardia frente a su máximo
semanal (`PA-Max`); quien se pasa sale en rojo.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import EditResult
from scheduling_platform.application.untis.supervision import (
    SupervisionCell,
    SupervisionFacade,
    SupervisionGrid,
    SupervisionLoad,
    SupervisionMixin,
)

from ..icons import icon, icon_size
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import BREAK_COLOR, ERROR_COLOR, day_name
from ..widgets.uikit import Banner, Legend, make_action, set_texts

#: Texto de "sin profesor" en los desplegables de la parrilla.
NO_TEACHER = "-"

#: Color de un turno ya cubierto.
COVERED_COLOR = "#dcfce7"

#: Columnas del resumen por profesor.
LOAD_COLUMNS = 4

#: La Fachada aún no hereda el mixin de guardias: mientras tanto, se usa suelto.
_SUPERVISION = SupervisionFacade()


class SupervisionWindow(QWidget):
    """Parrilla de guardias de recreo y resumen de minutos por profesor."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self._loading = False
        self.grid_view: SupervisionGrid | None = None
        self.cell_combos: dict[tuple[str, int, int], QComboBox] = {}

        self.toolbar = QToolBar()
        self.toolbar.setIconSize(icon_size("button"))
        self.add_action = make_action(self, "add", self.add_area)
        self.rename_action = make_action(self, "rename", self.rename_area)
        self.remove_action = make_action(self, "delete", self.remove_area)
        self.build_action = make_action(self, "grid_add", self.build_shifts)
        self.distribute_action = make_action(self, "optimize", self.distribute)
        self.unfix_action = make_action(self, "unfix", self.unfix_selected)
        self.clear_action = make_action(self, "unplace", self.clear_selected)
        for accion in (
            self.add_action,
            self.rename_action,
            self.remove_action,
            self.build_action,
            self.distribute_action,
            self.unfix_action,
            self.clear_action,
        ):
            self.toolbar.addAction(accion)

        self.grid_label = QLabel()
        self.grid_combo = QComboBox()
        self.grid_combo.setMinimumWidth(140)
        self.grid_combo.currentIndexChanged.connect(self._on_grid)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        cabecera = self.table.horizontalHeader()
        cabecera.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.currentCellChanged.connect(lambda *_celda: self._update_state())

        self.load_box = QGroupBox()
        self.load_table = QTableWidget(0, LOAD_COLUMNS)
        self.load_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.load_table.verticalHeader().setVisible(False)
        self.load_table.setMinimumWidth(320)
        lateral = QVBoxLayout(self.load_box)
        lateral.addWidget(self.load_table)

        self.banner = Banner("tip")
        self.legend = Legend()

        superior = QHBoxLayout()
        superior.addWidget(self.toolbar)
        superior.addSpacing(12)
        superior.addWidget(self.grid_label)
        superior.addWidget(self.grid_combo)
        superior.addStretch(1)
        centro = QHBoxLayout()
        centro.addWidget(self.table, 1)
        centro.addWidget(self.load_box)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)
        raiz.addLayout(superior)
        raiz.addWidget(self.legend)
        raiz.addLayout(centro, 1)
        raiz.addWidget(self.banner)

        bridge.refreshed.connect(self.refresh)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()
        self.refresh()

    # --- estado --------------------------------------------------------------- #

    @property
    def grid_id(self) -> str:
        """Rejilla cuyos recreos se están repartiendo."""
        return str(self.grid_combo.currentData() or "")

    def facade(self) -> SupervisionMixin:
        """Fachada de guardias: la del proyecto si ya hereda el mixin."""
        servicio = self.bridge.service
        return servicio if isinstance(servicio, SupervisionMixin) else _SUPERVISION

    def selected_cell(self) -> SupervisionCell | None:
        """Turno de la celda seleccionada, si hay alguna."""
        vista = self.grid_view
        fila, columna = self.table.currentRow(), self.table.currentColumn()
        if vista is None or fila < 0 or columna < 0:
            return None
        if fila >= len(vista.areas) or columna >= len(vista.slots):
            return None
        hueco = vista.slots[columna]
        return vista.cell(vista.areas[fila].id, hueco.day, hueco.period)

    # --- carga ----------------------------------------------------------------- #

    def refresh(self) -> None:
        """Recarga las rejillas, la parrilla y el resumen."""
        self._loading = True
        try:
            self._load_grids()
        finally:
            self._loading = False
        self._load_table()
        self._load_summary()
        self._update_state()

    def _load_grids(self) -> None:
        actual = self.grid_id
        self.grid_combo.clear()
        if not self.bridge.has_session:
            return
        for g in self.bridge.service.grids(self.bridge.session):
            self.grid_combo.addItem(icon("time_grids"), g.name, g.id)
        posicion = self.grid_combo.findData(actual)
        if posicion >= 0:
            self.grid_combo.setCurrentIndex(posicion)

    def _load_table(self) -> None:
        self._loading = True
        # La celda elegida se conserva: tras editar, la parrilla se vuelve a
        # montar entera y la orden siguiente sigue hablando del mismo turno.
        seleccion = (self.table.currentRow(), self.table.currentColumn())
        try:
            self.cell_combos.clear()
            # `setRowCount(0)` destruye también los desplegables de las celdas.
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            if not self.bridge.has_session:
                self.grid_view = None
                return
            vista = self.facade().supervision_grid(self.bridge.session, self.grid_id)
            self.grid_view = vista
            self.table.setRowCount(len(vista.areas))
            self.table.setColumnCount(len(vista.slots))
            self.table.setHorizontalHeaderLabels(
                [f"{day_name(h.day, self.bridge.language)}\n{h.start}-{h.end}" for h in vista.slots]
            )
            self.table.setVerticalHeaderLabels([a.name for a in vista.areas])
            for fila, zona in enumerate(vista.areas):
                for columna, hueco in enumerate(vista.slots):
                    celda = vista.cell(zona.id, hueco.day, hueco.period)
                    self._fill_cell(fila, columna, celda, vista)
            fila, columna = seleccion
            if 0 <= fila < self.table.rowCount() and 0 <= columna < self.table.columnCount():
                self.table.setCurrentCell(fila, columna)
        finally:
            self._loading = False

    def _fill_cell(
        self, row: int, column: int, cell: SupervisionCell | None, view: SupervisionGrid
    ) -> None:
        """Pone el desplegable de profesor de una celda de la parrilla."""
        if cell is None or not cell.exists:
            hueco = QTableWidgetItem("")
            hueco.setBackground(QColor(BREAK_COLOR))
            hueco.setToolTip(self.tr("Sin turno: pulsa Generar turnos"))
            self.table.setItem(row, column, hueco)
            return
        combo = QComboBox()
        combo.addItem(NO_TEACHER, "")
        for profesor in view.teachers:
            combo.addItem(profesor, profesor)
        posicion = combo.findData(cell.teacher)
        combo.setCurrentIndex(posicion if posicion >= 0 else 0)
        if cell.fixed:
            combo.setItemIcon(combo.currentIndex(), icon("fix"))
        color = COVERED_COLOR if cell.assigned else ERROR_COLOR
        combo.setStyleSheet(f"QComboBox {{ background: {color}; }}")
        combo.setToolTip(
            self.tr("Profesor de guardia en {0}, {1} ({2} min). Vacío = sin cubrir.").format(
                cell.area, day_name(cell.day, self.bridge.language), cell.minutes
            )
        )
        clave = (cell.area, cell.day, cell.period)
        combo.currentIndexChanged.connect(lambda _i, c=clave: self._on_teacher(c))
        self.cell_combos[clave] = combo
        self.table.setCellWidget(row, column, combo)
        marca = QTableWidgetItem("")
        marca.setBackground(QColor(COVERED_COLOR if cell.assigned else ERROR_COLOR))
        self.table.setItem(row, column, marca)

    def _load_summary(self) -> None:
        cargas: tuple[SupervisionLoad, ...] = ()
        if self.bridge.has_session:
            cargas = self.facade().supervision_load(self.bridge.session)
        self.load_table.setRowCount(len(cargas))
        for fila, carga in enumerate(cargas):
            tope = self.tr("sin límite") if carga.maximum is None else str(carga.maximum)
            valores = (carga.name, str(carga.minutes), tope, str(carga.shifts))
            for columna, texto in enumerate(valores):
                celda = QTableWidgetItem(texto)
                if carga.over_max:
                    celda.setBackground(QColor(ERROR_COLOR))
                    celda.setToolTip(self.tr("Se pasa de su máximo de guardias"))
                self.load_table.setItem(fila, columna, celda)
        self.load_table.resizeColumnsToContents()

    def _update_state(self) -> None:
        """Activa las órdenes que tienen sentido ahora mismo."""
        vista = self.grid_view
        hay = self.bridge.has_session
        celda = self.selected_cell()
        self.add_action.setEnabled(hay)
        self.rename_action.setEnabled(bool(vista and vista.areas))
        self.remove_action.setEnabled(bool(vista and vista.areas))
        self.build_action.setEnabled(hay)
        self.distribute_action.setEnabled(bool(vista and vista.cells))
        self.unfix_action.setEnabled(bool(celda and celda.fixed))
        self.clear_action.setEnabled(bool(celda and celda.assigned))
        if vista is not None and vista.message:
            self.banner.show_message(vista.message, "warning")
        else:
            self.banner.show_message(self._hint(), "tip")

    def _hint(self) -> str:
        vista = self.grid_view
        if vista is None or not vista.cells:
            return self.tr(
                "Crea las zonas que hay que vigilar y pulsa Generar turnos: saldrá una "
                "casilla por zona y recreo de cada día."
            )
        return self.tr(
            "Elige el profesor de cada turno o pulsa Repartir guardias. Solo puede vigilar "
            "quien da clase justo antes o justo después del recreo. Sin cubrir: {0}."
        ).format(vista.uncovered)

    # --- órdenes ---------------------------------------------------------------- #

    def add_area(self) -> EditResult:
        """Pide el nombre corto de una zona nueva y la crea."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        nombre, aceptado = QInputDialog.getText(
            self, self.tr("Nueva zona de vigilancia"), self.tr("Nombre corto de la zona:")
        )
        if not aceptado:
            return EditResult.failure("")
        return self.create_area(nombre)

    def create_area(self, area_id: str, name: str = "") -> EditResult:
        """Crea una zona en la rejilla visible (sin diálogo: lo usan las pruebas)."""
        fachada, rejilla = self.facade(), self.grid_id
        resultado = self.bridge.edit(
            lambda: fachada.add_supervision_area(
                self.bridge.session, area_id, name=name, time_grid=rejilla
            )
        )
        self.refresh()
        return resultado

    def rename_area(self) -> EditResult:
        """Cambia el nombre largo de la zona de la fila seleccionada."""
        zona = self._selected_area()
        if zona is None:
            return EditResult.failure(self.tr("Elige antes una zona"))
        nombre, aceptado = QInputDialog.getText(
            self, self.tr("Renombrar zona"), self.tr("Nombre de la zona:"), text=zona
        )
        if not aceptado:
            return EditResult.failure("")
        fachada = self.facade()
        resultado = self.bridge.edit(
            lambda: fachada.rename_supervision_area(self.bridge.session, zona, nombre)
        )
        self.refresh()
        return resultado

    def remove_area(self) -> EditResult:
        """Borra la zona seleccionada con todos sus turnos."""
        zona = self._selected_area()
        if zona is None:
            return EditResult.failure(self.tr("Elige antes una zona"))
        fachada = self.facade()
        resultado = self.bridge.edit(
            lambda: fachada.remove_supervision_area(self.bridge.session, zona)
        )
        self.refresh()
        return resultado

    def build_shifts(self) -> EditResult:
        """Crea los turnos vacíos que falten en la rejilla visible."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        fachada, rejilla = self.facade(), self.grid_id
        resultado = self.bridge.edit(
            lambda: fachada.build_supervision_shifts(self.bridge.session, rejilla)
        )
        self.refresh()
        return resultado

    def distribute(self) -> EditResult:
        """Reparte los turnos sin profesor (equilibrando minutos)."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        fachada = self.facade()
        resultado = self.bridge.edit(lambda: fachada.distribute_supervisions(self.bridge.session))
        self.refresh()
        if resultado.message:
            self.banner.show_message(resultado.message, "ok" if resultado.ok else "error")
        return resultado

    def clear_selected(self) -> EditResult:
        """Quita el profesor del turno seleccionado."""
        celda = self.selected_cell()
        if celda is None:
            return EditResult.failure(self.tr("Elige antes un turno"))
        return self.set_teacher(celda.area, celda.day, celda.period, "")

    def unfix_selected(self) -> EditResult:
        """Suelta el turno seleccionado para que el reparto pueda moverlo."""
        celda = self.selected_cell()
        if celda is None:
            return EditResult.failure(self.tr("Elige antes un turno"))
        fachada = self.facade()
        resultado = self.bridge.edit(
            lambda: fachada.set_supervision_fixed(
                self.bridge.session, celda.area, celda.day, celda.period, False
            )
        )
        self.refresh()
        return resultado

    def set_teacher(self, area: str, day: int, period: int, teacher: str) -> EditResult:
        """Pone el profesor de un turno (vacío lo deja sin cubrir)."""
        fachada = self.facade()
        resultado = self.bridge.edit(
            lambda: fachada.set_supervision_teacher(self.bridge.session, area, day, period, teacher)
        )
        self.refresh()
        if not resultado.ok:
            self.banner.show_message(resultado.message, "error")
        return resultado

    def _on_teacher(self, key: tuple[str, int, int]) -> None:
        if self._loading:
            return
        combo = self.cell_combos.get(key)
        if combo is None:
            return
        self.set_teacher(key[0], key[1], key[2], str(combo.currentData() or ""))

    def _on_grid(self, _index: int) -> None:
        if not self._loading:
            self._load_table()
            self._load_summary()
            self._update_state()

    def _selected_area(self) -> str | None:
        vista = self.grid_view
        fila = self.table.currentRow()
        if vista is None or not 0 <= fila < len(vista.areas):
            return None
        return vista.areas[fila].id

    # --- idioma ------------------------------------------------------------------ #

    def _retranslate(self) -> None:
        set_texts(
            self.add_action,
            self.tr("Nueva zona"),
            self.tr("Crea una zona que vigilar en los recreos (patio, pasillo, comedor...)"),
        )
        set_texts(
            self.rename_action,
            self.tr("Renombrar"),
            self.tr("Cambia el nombre largo de la zona seleccionada"),
        )
        set_texts(
            self.remove_action,
            self.tr("Borrar zona"),
            self.tr("Borra la zona seleccionada y todos sus turnos de guardia"),
        )
        set_texts(
            self.build_action,
            self.tr("Generar turnos"),
            self.tr("Crea un turno vacío por zona, día y recreo de esta rejilla"),
        )
        set_texts(
            self.distribute_action,
            self.tr("Repartir guardias"),
            self.tr(
                "Asigna los turnos sin profesor equilibrando minutos, entre quienes dan "
                "clase justo antes o después del recreo"
            ),
        )
        set_texts(
            self.unfix_action,
            self.tr("Soltar turno"),
            self.tr("Quita la chincheta: el reparto automático podrá cambiar este turno"),
        )
        set_texts(
            self.clear_action,
            self.tr("Quitar profesor"),
            self.tr("Deja el turno seleccionado sin nadie de guardia"),
        )
        self.grid_label.setText(self.tr("Rejilla:"))
        self.grid_combo.setToolTip(
            self.tr("Rejilla de tiempo cuyos recreos se reparten en esta parrilla")
        )
        self.table.setToolTip(
            self.tr("Una fila por zona y una columna por recreo de cada día lectivo")
        )
        self.load_box.setTitle(self.tr("Minutos de guardia por profesor"))
        self.load_table.setHorizontalHeaderLabels(
            [self.tr("Profesor"), self.tr("Minutos"), self.tr("Máximo"), self.tr("Turnos")]
        )
        self.load_table.setToolTip(
            self.tr("Minutos de guardia a la semana frente al máximo de cada profesor")
        )
        self.legend.set_items(
            [
                (("fill", COVERED_COLOR), self.tr("turno cubierto")),
                (("fill", ERROR_COLOR), self.tr("sin cubrir")),
                (("fill", BREAK_COLOR), self.tr("sin turno")),
                (("icon", "fix"), self.tr("puesto a mano (no se mueve)")),
            ],
            self.tr("Leyenda:"),
        )
        self._load_table()
        self._load_summary()
        self._update_state()


register(
    WindowSpec(
        key="supervision",
        title="Guardias de recreo",
        title_de="Pausenaufsichten",
        tab=RibbonTab.MODULES,
        factory=SupervisionWindow,
        order=2,
        icon="break",
        tooltip=(
            "Reparte la vigilancia de los recreos: zonas, turnos de cada día y minutos "
            "de guardia de cada profesor."
        ),
        tooltip_de=(
            "Verteilt die Pausenaufsichten: Aufsichtsbereiche, Aufsichten je Tag und Minuten "
            "je Lehrkraft."
        ),
    )
)
