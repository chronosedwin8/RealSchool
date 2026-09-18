"""Ventana Deseos de tiempo: valores -3..+3 por celda, por día y por entidad.

Se elige el tipo (clase, profesor, aula, materia) y la entidad; la ventana sigue
la selección sincronizada, así que al elegir una clase en Datos maestros (o
pulsar "Deseos" en su fila) se enfoca aquí. Una paleta fija el valor que pinta
el clic o el arrastre; el clic en la cabecera del día fija el deseo del día.
El cuadro de deseos no especificados guarda "N días/mañanas/tardes libres".
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import EditResult

from ..icons import icon
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import BREAK_COLOR, REQUEST_COLORS, request_color, text_color_for
from ..widgets.master_grid import KIND_OF_SELECTION, entity_ids
from ..widgets.request_grid import RequestCell, RequestGridWidget, request_meaning, request_text
from ..widgets.uikit import Banner, Legend, exempt

#: Tipos de entidad con deseos, en el orden del desplegable.
REQUEST_KINDS: tuple[str, ...] = ("class", "teacher", "room", "subject")

#: Tipos de deseo no especificado (Fachada `set_unspecified`).
UNSPECIFIED_KINDS: tuple[str, ...] = ("free_day", "free_morning", "free_afternoon")

#: Valores de la paleta.
PALETTE: tuple[int, ...] = (-3, -2, -1, 0, 1, 2, 3)
#: Desplazamiento de los ids del grupo de botones: `QButtonGroup` reserva el
#: id -1 ("asigna tú uno"), así que el valor -1 no puede ser su propio id.
PALETTE_ID_OFFSET = 10


class RequestsWindow(QWidget):
    """Deseos de tiempo de una clase, profesor, aula o materia."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self._loading = False

        self.kind_label = QLabel()
        self.kind_combo = QComboBox()
        iconos = {"class": "classes", "teacher": "teachers", "room": "rooms", "subject": "subjects"}
        for kind in REQUEST_KINDS:
            self.kind_combo.addItem(icon(iconos[kind]), kind, kind)
        self.kind_combo.currentIndexChanged.connect(self._on_kind)
        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(140)
        self.entity_combo.currentIndexChanged.connect(self._on_entity)

        self.palette_label = QLabel()
        self.palette_group = QButtonGroup(self)
        self.palette_group.setExclusive(True)
        self.palette_buttons: dict[int, QToolButton] = {}
        paleta = QHBoxLayout()
        paleta.setSpacing(2)
        for valor in PALETTE:
            boton = QToolButton()
            boton.setCheckable(True)
            boton.setText(request_text(valor) or "0")
            boton.setMinimumWidth(34)
            color = request_color(valor)
            texto = text_color_for(color).name()
            exempt(boton, "el texto es el valor del deseo")
            boton.setStyleSheet(
                f"QToolButton {{ background: {color.name()}; color: {texto}; }}"
                "QToolButton:checked { border: 2px solid #111827; font-weight: bold; }"
            )
            self.palette_group.addButton(boton, valor + PALETTE_ID_OFFSET)
            self.palette_buttons[valor] = boton
            paleta.addWidget(boton)
        self.palette_group.idClicked.connect(
            lambda ident: self.set_paint_value(ident - PALETTE_ID_OFFSET)
        )

        self.grid = RequestGridWidget()
        self.grid.painted.connect(self._on_painted)
        self.hint = Banner("tip")
        self.legend = Legend()

        self.unspecified_box = QGroupBox()
        no_especificados = QFormLayout(self.unspecified_box)
        self.unspecified: dict[str, QSpinBox] = {}
        self.unspecified_labels: dict[str, QLabel] = {}
        for tipo in UNSPECIFIED_KINDS:
            caja = QSpinBox()
            caja.setRange(0, 7)
            caja.valueChanged.connect(lambda n, t=tipo: self._on_unspecified(t, n))
            etiqueta = QLabel()
            no_especificados.addRow(etiqueta, caja)
            self.unspecified[tipo] = caja
            self.unspecified_labels[tipo] = etiqueta

        barra = QHBoxLayout()
        barra.addWidget(self.kind_label)
        barra.addWidget(self.kind_combo)
        barra.addWidget(self.entity_combo)
        barra.addSpacing(16)
        barra.addWidget(self.palette_label)
        barra.addLayout(paleta)
        barra.addStretch(1)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)
        raiz.addLayout(barra)
        centro = QHBoxLayout()
        centro.addWidget(self.grid, 1)
        lateral = QVBoxLayout()
        lateral.addWidget(self.unspecified_box)
        lateral.addStretch(1)
        centro.addLayout(lateral)
        raiz.addWidget(self.legend)
        raiz.addLayout(centro, 1)
        raiz.addWidget(self.hint)

        bridge.refreshed.connect(self.refresh)
        bridge.selection_changed.connect(self.focus_entity)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self.set_paint_value(-3)
        self._retranslate()
        self.refresh()
        if bridge.selection is not None:
            self.focus_entity(*bridge.selection)

    # --- estado ------------------------------------------------------------- #

    @property
    def kind(self) -> str:
        return str(self.kind_combo.currentData() or REQUEST_KINDS[0])

    @property
    def entity(self) -> str:
        return self.entity_combo.currentText()

    def set_paint_value(self, value: int) -> None:
        self.grid.paint_value = value
        boton = self.palette_buttons.get(value)
        if boton is not None and not boton.isChecked():
            boton.setChecked(True)

    def refresh(self) -> None:
        """Recarga la lista de entidades (conservando la actual) y la rejilla."""
        self._loading = True
        try:
            actual = self.entity
            ids = entity_ids(self.bridge, KIND_OF_SELECTION[self.kind])
            self.entity_combo.clear()
            self.entity_combo.addItems(list(ids))
            if actual in ids:
                self.entity_combo.setCurrentIndex(ids.index(actual))
        finally:
            self._loading = False
        self._load_grid()

    def _load_grid(self) -> None:
        activo = self.bridge.has_session and bool(self.entity)
        cantidades: dict[str, int] = {}
        if activo:
            svc, s = self.bridge.service, self.bridge.session
            self.grid.set_grid(svc.request_grid(s, self.kind, self.entity), self.bridge.language)
            cantidades = dict(svc.unspecified_requests(s, self.kind, self.entity))
        else:
            self.grid.set_grid(None, self.bridge.language)
        for tipo, caja in self.unspecified.items():
            caja.blockSignals(True)
            caja.setValue(cantidades.get(tipo, 0))
            caja.blockSignals(False)
            caja.setEnabled(activo)

    def focus_entity(self, kind: str, entity_id: str) -> None:
        """Muestra los deseos de `entity_id` (selección sincronizada)."""
        if kind not in REQUEST_KINDS:
            return
        if kind != self.kind:
            self._loading = True
            try:
                self.kind_combo.setCurrentIndex(REQUEST_KINDS.index(kind))
            finally:
                self._loading = False
            self.refresh()
        posicion = self.entity_combo.findText(entity_id)
        if posicion >= 0 and posicion != self.entity_combo.currentIndex():
            self.entity_combo.setCurrentIndex(posicion)

    def _on_kind(self, _index: int) -> None:
        if not self._loading:
            self.refresh()

    def _on_entity(self, _index: int) -> None:
        if self._loading:
            return
        self._load_grid()
        if self.entity:
            self.bridge.select(self.kind, self.entity)

    # --- edición ------------------------------------------------------------ #

    def _on_painted(self, cells: object, value: int) -> None:
        if isinstance(cells, list):
            self.paint(cells, value)

    def paint(self, cells: list[RequestCell], value: int) -> EditResult:
        """Fija `value` en las celdas (período `None` = día completo)."""
        if not self.bridge.has_session or not self.entity:
            return EditResult.failure(self.tr("Elige una entidad"))
        svc, kind, entidad = self.bridge.service, self.kind, self.entity

        def aplicar() -> EditResult:
            ultimo = EditResult.success()
            for dia, periodo in cells:
                r = svc.set_request(self.bridge.session, kind, entidad, dia, periodo, value)
                if not r.ok:
                    return r
                ultimo = r
            return ultimo

        resultado = self.bridge.edit(aplicar)
        if not resultado.ok:
            self._load_grid()
        return resultado

    def _on_unspecified(self, request_kind: str, count: int) -> None:
        self.set_unspecified(request_kind, count)

    def set_unspecified(self, request_kind: str, count: int) -> EditResult:
        """Fija "N días/mañanas/tardes libres" de la entidad (0 lo borra)."""
        if not self.bridge.has_session or not self.entity:
            return EditResult.failure(self.tr("Elige una entidad"))
        svc, kind, entidad = self.bridge.service, self.kind, self.entity
        resultado = self.bridge.edit(
            lambda: svc.set_unspecified(self.bridge.session, kind, entidad, request_kind, count)
        )
        if not resultado.ok:
            self._load_grid()
        return resultado

    def set_day(self, day: int, value: int) -> EditResult:
        """Deseo de día completo."""
        return self.paint([(day, None)], value)

    # --- idioma --------------------------------------------------------------- #

    def _retranslate(self) -> None:
        nombres = {
            "class": self.tr("Clase"),
            "teacher": self.tr("Profesor"),
            "room": self.tr("Aula"),
            "subject": self.tr("Materia"),
        }
        for i, kind in enumerate(REQUEST_KINDS):
            self.kind_combo.setItemText(i, nombres[kind])
        self.kind_label.setText(self.tr("Deseos de:"))
        self.palette_label.setText(self.tr("Valor:"))
        self.unspecified_box.setTitle(self.tr("Deseos no especificados"))
        textos = {
            "free_day": self.tr("Días libres"),
            "free_morning": self.tr("Mañanas libres"),
            "free_afternoon": self.tr("Tardes libres"),
        }
        ayudas = {
            "free_day": self.tr("Cuántos días enteros libres quiere a la semana, sin decir cuáles"),
            "free_morning": self.tr("Cuántas mañanas libres quiere a la semana, sin decir cuáles"),
            "free_afternoon": self.tr("Cuántas tardes libres quiere a la semana, sin decir cuáles"),
        }
        for tipo, etiqueta in self.unspecified_labels.items():
            etiqueta.setText(textos[tipo])
            etiqueta.setToolTip(ayudas[tipo])
            self.unspecified[tipo].setToolTip(ayudas[tipo])
        self.kind_combo.setToolTip(
            self.tr("De quién son los deseos: clase, profesor, aula o materia")
        )
        self.entity_combo.setToolTip(
            self.tr("La clase, profesor, aula o materia cuyos deseos editas")
        )
        for valor in PALETTE:
            boton = self.palette_buttons.get(valor)
            if boton is not None:
                boton.setToolTip(
                    self.tr("{0}. Elige este valor y pinta las celdas con clic o arrastre").format(
                        request_meaning(valor)
                    )
                )
        self.legend.set_items(
            [
                (("fill", REQUEST_COLORS[-3]), self.tr("-3 imposible")),
                (("fill", REQUEST_COLORS[-1]), self.tr("-1/-2 mejor no")),
                (("fill", REQUEST_COLORS[0]), self.tr("0 sin deseo")),
                (("fill", REQUEST_COLORS[1]), self.tr("+1/+2 mejor aquí")),
                (("fill", REQUEST_COLORS[3]), self.tr("+3 muy deseable")),
                (("fill", BREAK_COLOR), self.tr("recreo")),
            ],
            self.tr("Leyenda:"),
        )
        self.hint.setText(
            self.tr(
                "Elige un valor en la paleta y pinta con clic o arrastrando. Clic derecho: borra. "
                "Clic en el nombre del día: deseo para el día entero."
            )
        )
        self._load_grid()


register(
    WindowSpec(
        key="requests",
        title="Deseos de tiempo",
        title_de="Zeitwünsche",
        tab=RibbonTab.MASTER_DATA,
        factory=RequestsWindow,
        order=8,
        icon="requests",
        tooltip="Marca cuándo puede y cuándo no tener clase cada profesor, clase, aula o materia.",
        tooltip_de=(
            "Legt fest, wann jede Lehrkraft, Klasse, jeder Raum oder jedes Fach Unterricht haben "
            "kann und wann nicht."
        ),
    )
)
