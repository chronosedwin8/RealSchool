"""Ventana Ponderación: deslizadores 0-5 por pestaña y pestaña Análisis.

Una página por `WeightingTabView` de la Fachada. Cada deslizador muestra su
etiqueta (es/de), el valor y el peso resultante; la ayuda sale como ayuda
emergente y en el panel inferior al pasar el ratón o enfocar. La pestaña
Análisis es la contribución de cada criterio al número de evaluación del horario
activo, ordenada de mayor a menor.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import EditResult, SliderView, WeightingTabView

from ..icons import icon
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import fmt_int
from ..widgets.uikit import Banner, set_texts, tool_button

#: Pestaña de la Fachada que no tiene deslizadores: aquí va la tabla de análisis.
ANALYSIS_TAB = "analysis"

#: Icono de cada pestaña de Ponderación.
TAB_ICONS: dict[str, str] = {
    "teachers_1": "teachers",
    "teachers_2": "teachers",
    "classes": "classes",
    "subjects": "subjects",
    "main_subjects": "tip",
    "rooms": "rooms",
    "period_distribution": "timetables",
    "time_requests": "requests",
    "analysis": "analysis",
}

#: Rol con el valor numérico de una celda de la tabla Análisis.
VALUE_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass(slots=True)
class SliderRow:
    """Los widgets de un criterio."""

    view: SliderView
    label: QLabel
    slider: QSlider
    value: QLabel


class WeightingWindow(QWidget):
    """Ponderación de criterios del proyecto."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.tabs = QTabWidget()
        self.help = QTextBrowser()
        self.help.setMaximumHeight(90)
        self.message = Banner("warning")
        self.message.hide()
        self.reset_button = tool_button("undo", self.reset_defaults)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.intro.setStyleSheet("color: #4b5563;")
        self.analysis = QTableWidget(0, 6)
        self.analysis.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.analysis.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.analysis.verticalHeader().setVisible(False)
        self.analysis.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.analysis.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.analysis_total = QLabel()
        self.sliders: dict[str, SliderRow] = {}
        self._views: tuple[WeightingTabView, ...] = ()
        self._pages: dict[str, int] = {}
        self._analysis_dirty = True
        self._analysis_page = QWidget()
        pagina = QVBoxLayout(self._analysis_page)
        pagina.addWidget(self.analysis_total)
        pagina.addWidget(self.analysis, 1)

        arriba = QHBoxLayout()
        arriba.addWidget(self.intro, 1)
        arriba.addWidget(self.reset_button)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(4, 4, 4, 4)
        raiz.addLayout(arriba)
        raiz.addWidget(self.tabs, 1)
        raiz.addWidget(self.message)
        raiz.addWidget(self.help)
        self.tabs.currentChanged.connect(lambda _i: self._fill_analysis_if_visible())
        bridge.refreshed.connect(self.refresh)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self.refresh()
        self._retranslate()

    # --- construcción --------------------------------------------------------- #

    def _build(self, views: tuple[WeightingTabView, ...]) -> None:
        viejas = [self.tabs.widget(i) for i in range(self.tabs.count())]
        self.tabs.clear()
        for pagina_vieja in viejas:
            if pagina_vieja is not None and pagina_vieja is not self._analysis_page:
                pagina_vieja.deleteLater()
        self.sliders = {}
        self._pages = {}
        for vista in views:
            if vista.tab == ANALYSIS_TAB or not vista.sliders:
                continue
            pagina = QWidget()
            rejilla = QGridLayout(pagina)
            for fila, sv in enumerate(vista.sliders):
                etiqueta = QLabel()
                deslizador = QSlider(Qt.Orientation.Horizontal)
                deslizador.setRange(0, 5)
                deslizador.setPageStep(1)
                deslizador.setTickPosition(QSlider.TickPosition.TicksBelow)
                deslizador.setTickInterval(1)
                deslizador.setMinimumWidth(180)
                deslizador.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                deslizador.setProperty("criterion", sv.criterion)
                deslizador.installEventFilter(self)
                etiqueta.installEventFilter(self)
                etiqueta.setProperty("criterion", sv.criterion)
                valor = QLabel()
                valor.setMinimumWidth(170)
                deslizador.valueChanged.connect(
                    lambda v, c=sv.criterion: self._on_value_changed(c, v)
                )
                deslizador.sliderReleased.connect(lambda c=sv.criterion: self._on_released(c))
                rejilla.addWidget(etiqueta, fila, 0)
                rejilla.addWidget(deslizador, fila, 1)
                rejilla.addWidget(valor, fila, 2)
                self.sliders[sv.criterion] = SliderRow(sv, etiqueta, deslizador, valor)
            rejilla.setRowStretch(len(vista.sliders), 1)
            rejilla.setColumnStretch(1, 1)
            self._pages[vista.tab] = self.tabs.addTab(
                pagina, icon(TAB_ICONS.get(vista.tab, "weighting")), ""
            )
        self._pages[ANALYSIS_TAB] = self.tabs.addTab(self._analysis_page, icon("analysis"), "")

    def refresh(self) -> None:
        views = (
            self.bridge.service.weighting_tabs(self.bridge.session)
            if self.bridge.has_session
            else ()
        )
        estructura = [(v.tab, [s.criterion for s in v.sliders]) for v in views]
        if estructura != [(v.tab, [s.criterion for s in v.sliders]) for v in self._views] or (
            not self._pages
        ):
            actual = self.tabs.currentIndex()
            self._build(views)
            if 0 <= actual < self.tabs.count():
                self.tabs.setCurrentIndex(actual)
        self._views = views
        for vista in views:
            for sv in vista.sliders:
                fila = self.sliders.get(sv.criterion)
                if fila is None:
                    continue
                fila.view = sv
                fila.slider.blockSignals(True)
                fila.slider.setValue(sv.value)
                fila.slider.blockSignals(False)
                fila.slider.setEnabled(self.bridge.has_session)
        self._update_texts()
        self._analysis_dirty = True
        self._fill_analysis_if_visible()

    # --- edición ------------------------------------------------------------------ #

    def _on_value_changed(self, criterion: str, value: int) -> None:
        fila = self.sliders[criterion]
        if fila.slider.isSliderDown():
            fila.value.setText(self.level_name(value))
            return
        self.set_value(criterion, value)

    def _on_released(self, criterion: str) -> None:
        fila = self.sliders[criterion]
        self.set_value(criterion, fila.slider.value())

    def set_value(self, criterion: str, value: int) -> EditResult:
        """Fija un deslizador; muestra el aviso de la Fachada si lo hay."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        fila = self.sliders.get(criterion)
        if fila is not None and fila.view.value == value:
            return EditResult.success()
        svc = self.bridge.service
        resultado = self.bridge.edit(lambda: svc.set_slider(self.bridge.session, criterion, value))
        self.message.show_message(resultado.message, "warning" if resultado.ok else "error")
        if not resultado.ok and fila is not None:
            fila.slider.blockSignals(True)
            fila.slider.setValue(fila.view.value)
            fila.slider.blockSignals(False)
        return resultado

    def defaults(self) -> dict[str, int]:
        """Valores de fábrica de los deslizadores (los de un proyecto nuevo)."""
        return self.bridge.service.default_weighting()

    def reset_defaults(self) -> EditResult:
        """Vuelve a poner todos los deslizadores en su valor de fábrica."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        svc = self.bridge.service
        fabrica = self.defaults()
        actuales = {
            sv.criterion: sv.value
            for v in svc.weighting_tabs(self.bridge.session)
            for sv in v.sliders
        }
        cambios = {c: v for c, v in fabrica.items() if actuales.get(c) != v}
        if not cambios:
            self.message.show_message(self.tr("Ya están los valores por defecto."), "ok")
            return EditResult.success()

        resultado = self.bridge.edit(lambda: svc.reset_weighting(self.bridge.session))
        if resultado.ok:
            self.message.show_message(
                self.tr("Restablecidos {0} criterio(s) a su valor por defecto.").format(
                    len(cambios)
                ),
                "ok",
            )
        else:
            self.message.show_message(resultado.message, "error")
        self.refresh()
        return resultado

    # --- ayuda -------------------------------------------------------------------- #

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Enter, QEvent.Type.FocusIn):
            criterio = watched.property("criterion")
            if isinstance(criterio, str):
                self.show_help(criterio)
        return super().eventFilter(watched, event)

    def show_help(self, criterion: str) -> None:
        fila = self.sliders.get(criterion)
        if fila is None:
            return
        self.help.setPlainText(f"{self._label(fila.view)}\n\n{fila.view.help}")

    # --- textos ---------------------------------------------------------------------- #

    def _label(self, view: SliderView) -> str:
        return view.label_de if self.bridge.language == "de" else view.label

    def level_name(self, value: int) -> str:
        """Nombre de una posición del deslizador (0 = Desactivado ... 5 = Máximo)."""
        nombres = {
            0: self.tr("Desactivado"),
            1: self.tr("Muy bajo"),
            2: self.tr("Bajo"),
            3: self.tr("Medio"),
            4: self.tr("Alto"),
            5: self.tr("Máximo"),
        }
        return self.tr("{0} ({1})").format(nombres.get(value, str(value)), value)

    def value_text(self, view: SliderView) -> str:
        """Texto junto al deslizador: "Medio (3) · peso 10"."""
        return self.tr("{0} · peso {1}").format(self.level_name(view.value), fmt_int(view.weight))

    def _update_texts(self) -> None:
        for fila in self.sliders.values():
            texto = self._label(fila.view)
            fila.label.setText(texto)
            fila.label.setToolTip(fila.view.help)
            fila.slider.setToolTip(fila.view.help)
            fila.value.setText(self.value_text(fila.view))
            fila.value.setToolTip(
                self.tr("Posición del deslizador y peso con que cuenta cada violación")
            )
        for vista in self._views:
            indice = self._pages.get(vista.tab)
            if indice is not None and vista.tab != ANALYSIS_TAB:
                self.tabs.setTabText(
                    indice, vista.label_de if self.bridge.language == "de" else vista.label
                )
        indice = self._pages.get(ANALYSIS_TAB)
        if indice is not None:
            self.tabs.setTabText(indice, self.tr("Análisis"))

    def show_analysis(self) -> None:
        """Muestra la pestaña Análisis (y la calcula)."""
        self.tabs.setCurrentWidget(self._analysis_page)
        self._fill_analysis_if_visible()

    def _fill_analysis_if_visible(self) -> None:
        """El análisis evalúa el horario entero: solo se calcula si se está viendo."""
        if self._analysis_dirty and self.tabs.currentWidget() is self._analysis_page:
            self._fill_analysis()

    def _fill_analysis(self) -> None:
        self._analysis_dirty = False
        self.analysis.setRowCount(0)
        if not self.bridge.has_session:
            self.analysis_total.setText("")
            return
        evaluacion = self.bridge.service.evaluation(self.bridge.session)
        if evaluacion is None:
            self.analysis_total.setText(self.tr("Sin horario activo: no hay nada que analizar"))
            return
        self.analysis_total.setText(
            self.tr("Número de evaluación {0}: {1} sin colocar, {2} choque(s)").format(
                fmt_int(evaluacion.total),
                fmt_int(evaluacion.unplaced_periods),
                fmt_int(evaluacion.clashes),
            )
        )
        etiquetas = {sv.criterion: self._label(sv) for v in self._views for sv in v.sliders}
        pestanas = {
            v.tab: (v.label_de if self.bridge.language == "de" else v.label) for v in self._views
        }
        lineas = sorted(evaluacion.criteria, key=lambda c: (-c.points, c.criterion))
        self.analysis.setRowCount(len(lineas))
        for fila, c in enumerate(lineas):
            valores: tuple[str | int, ...] = (
                etiquetas.get(c.criterion, c.label),
                pestanas.get(c.tab, c.tab),
                c.slider,
                c.weight,
                c.violations,
                c.points,
            )
            for col, valor in enumerate(valores):
                item = QTableWidgetItem(fmt_int(valor) if isinstance(valor, int) else valor)
                if isinstance(valor, int):
                    item.setData(VALUE_ROLE, valor)
                if col == 1:
                    item.setIcon(icon(TAB_ICONS.get(c.tab, "weighting")))
                if col >= 2:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                item.setData(Qt.ItemDataRole.UserRole, c.criterion)
                self.analysis.setItem(fila, col, item)

    def analysis_rows(self) -> list[tuple[str, int]]:
        """`(criterio, puntos)` de la tabla Análisis, en orden (pruebas)."""
        filas: list[tuple[str, int]] = []
        for fila in range(self.analysis.rowCount()):
            item = self.analysis.item(fila, 5)
            if item is not None:
                filas.append((str(item.data(Qt.ItemDataRole.UserRole)), int(item.data(VALUE_ROLE))))
        return filas

    def _retranslate(self) -> None:
        self.analysis.setHorizontalHeaderLabels(
            [
                self.tr("Criterio"),
                self.tr("Pestaña"),
                self.tr("Deslizador"),
                self.tr("Peso"),
                self.tr("Violaciones"),
                self.tr("Puntos"),
            ]
        )
        self.help.setPlaceholderText(
            self.tr("Pasa el ratón por un criterio para ver su explicación.")
        )
        self.intro.setText(
            self.tr(
                "Cuánto importa cada criterio al optimizar: 0 = no se tiene en cuenta, "
                "5 = lo más importante. Usa el 5 para muy pocos criterios."
            )
        )
        set_texts(
            self.reset_button,
            self.tr("Restablecer valores por defecto"),
            self.tr("Vuelve a poner todos los deslizadores como en un proyecto nuevo"),
        )
        self._update_texts()
        self._analysis_dirty = True
        self._fill_analysis_if_visible()


register(
    WindowSpec(
        key="weighting",
        title="Ponderación",
        title_de="Gewichtung",
        tab=RibbonTab.MODULES,
        factory=WeightingWindow,
        order=1,
        icon="weighting",
        tooltip="Decide cuánto pesa cada criterio (huecos, dobles, deseos...) al optimizar.",
        tooltip_de=(
            "Legt fest, wie stark jedes Kriterium (Hohlstunden, Doppelstunden, Wünsche...) beim "
            "Optimieren zählt."
        ),
    )
)
