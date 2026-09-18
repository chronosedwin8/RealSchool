"""Ventana Evaluación: número de evaluación, desglose y horarios generados.

Como en Untis, el número de evaluación es la suma ponderada de violaciones del
horario activo; debajo va el desglose por criterio (ordenado por contribución)
y el subtotal por pestaña de Ponderación. La lista de horarios generados por la
Optimización permite activar uno, borrarlo o comparar dos lado a lado.

Las cifras llevan separador de miles y un icono de estado (correcto, aviso o
error) para leerlas de un vistazo.
"""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import (
    CRITERION_TEXTS,
    TAB_LABELS,
    EditResult,
    EvaluationView,
    TimetableSummary,
)

from ..icons import icon
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import fmt_int
from ..widgets.uikit import Banner, icon_pixmap, set_texts, tool_button

#: Rol con el valor numérico de una celda.
VALUE_ROLE = Qt.ItemDataRole.UserRole + 5
#: Tamaño del icono de estado junto al número de evaluación.
STATUS_SIZE = QSize(40, 40)


def fmt_signed(value: int) -> str:
    """Diferencia con signo y separador de miles (`+1.234`, `-56`, `0`)."""
    return f"+{fmt_int(value)}" if value > 0 else fmt_int(value)


def status_of(view: EvaluationView) -> str:
    """Icono de estado de una evaluación: `error` (choques), `warning` (sin colocar) u `ok`."""
    if view.clashes:
        return "error"
    if view.unplaced_periods:
        return "warning"
    return "ok"


def _item(value: object, *, align_right: bool = False) -> QTableWidgetItem:
    texto = fmt_int(value) if isinstance(value, int) and not isinstance(value, bool) else value
    item = QTableWidgetItem(str(texto))
    if isinstance(value, int):
        item.setData(VALUE_ROLE, value)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _table(columns: int) -> QTableWidget:
    tabla = QTableWidget(0, columns)
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabla.verticalHeader().setVisible(False)
    cabecera = tabla.horizontalHeader()
    cabecera.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    cabecera.setStretchLastSection(False)
    return tabla


def _stretch(tabla: QTableWidget, column: int) -> None:
    """La columna de texto se estira; las numéricas se ajustan a su contenido."""
    tabla.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)


class EvaluationWindow(QWidget):
    """Evaluación del horario activo y lista de horarios generados."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.view: EvaluationView | None = None
        self.summaries: tuple[TimetableSummary, ...] = ()
        self._stale = True

        # --- cifras -------------------------------------------------------- #
        self.summary_box = QGroupBox()
        cifras = QGridLayout(self.summary_box)
        self.total_label = QLabel("-")
        grande = QFont()
        grande.setPointSize(26)
        grande.setBold(True)
        self.total_label.setFont(grande)
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(STATUS_SIZE)
        self.status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_text = QLabel()
        self.status_text.setWordWrap(True)
        self.timetable_label = QLabel()
        self.unplaced_label = QLabel("-")
        self.clashes_label = QLabel("-")
        self.soft_label = QLabel("-")
        self._names = [QLabel() for _ in range(3)]
        grande_total = QHBoxLayout()
        grande_total.addWidget(self.status_icon)
        grande_total.addWidget(self.total_label)
        grande_total.addStretch(1)
        cifras.addLayout(grande_total, 0, 0, 3, 1)
        iconos = ("unplace", "error", "weighting")
        for fila, (nombre, valor) in enumerate(
            zip(
                self._names,
                (self.unplaced_label, self.clashes_label, self.soft_label),
                strict=True,
            )
        ):
            simbolo = QLabel()
            simbolo.setPixmap(icon_pixmap(iconos[fila]))
            cifras.addWidget(simbolo, fila, 1)
            cifras.addWidget(nombre, fila, 2)
            valor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            valor.setMinimumWidth(80)
            cifras.addWidget(valor, fila, 3)
        cifras.addWidget(self.timetable_label, 3, 0, 1, 4)
        cifras.addWidget(self.status_text, 0, 5, 4, 1)
        cifras.setColumnMinimumWidth(4, 24)
        cifras.setColumnStretch(5, 1)

        # --- desglose -------------------------------------------------------- #
        self.criteria_table = _table(6)
        _stretch(self.criteria_table, 0)
        self.tabs_table = _table(3)
        _stretch(self.tabs_table, 0)
        self.breakdown_box = QGroupBox()
        desglose = QSplitter(Qt.Orientation.Horizontal)
        desglose.addWidget(self.criteria_table)
        desglose.addWidget(self.tabs_table)
        desglose.setStretchFactor(0, 3)
        desglose.setStretchFactor(1, 1)
        QVBoxLayout(self.breakdown_box).addWidget(desglose)

        # --- horarios generados ------------------------------------------------ #
        self.timetables_box = QGroupBox()
        self.timetables_table = _table(6)
        _stretch(self.timetables_table, 2)
        self.timetables_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.timetables_table.itemSelectionChanged.connect(self._update_buttons)
        self.activate_button = tool_button("activate", lambda: self.activate_selected())
        self.delete_button = tool_button("delete", self.delete_selected)
        self.compare_button = tool_button("compare", lambda: self.compare_selected())
        self.timetables_hint = Banner("tip")
        self.timetables_hint.hide()
        botones = QHBoxLayout()
        for b in (self.activate_button, self.delete_button, self.compare_button):
            botones.addWidget(b)
        botones.addStretch(1)
        lista = QVBoxLayout(self.timetables_box)
        lista.addLayout(botones)
        lista.addWidget(self.timetables_hint)
        lista.addWidget(self.timetables_table)

        # --- comparación -------------------------------------------------------- #
        self.compare_box = QGroupBox()
        self.compare_table = _table(4)
        _stretch(self.compare_table, 0)
        QVBoxLayout(self.compare_box).addWidget(self.compare_table)
        self.compare_box.setVisible(False)
        self.compared: tuple[str, str] | None = None

        principal = QVBoxLayout(self)
        principal.addWidget(self.summary_box)
        cuerpo = QSplitter(Qt.Orientation.Vertical)
        cuerpo.addWidget(self.breakdown_box)
        cuerpo.addWidget(self.timetables_box)
        cuerpo.addWidget(self.compare_box)
        principal.addWidget(cuerpo, 1)

        bridge.refreshed.connect(self._on_refreshed)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()

    # --- textos ------------------------------------------------------------ #

    def _retranslate(self) -> None:
        self.summary_box.setTitle(self.tr("Número de evaluación"))
        for etiqueta, texto in zip(
            self._names,
            (self.tr("Períodos sin colocar"), self.tr("Choques"), self.tr("Puntos blandos")),
            strict=True,
        ):
            etiqueta.setText(texto)
        self.breakdown_box.setTitle(self.tr("Desglose por criterio"))
        self.criteria_table.setHorizontalHeaderLabels(
            [
                self.tr("Criterio"),
                self.tr("Pestaña"),
                self.tr("Deslizador"),
                self.tr("Peso"),
                self.tr("Violaciones"),
                self.tr("Puntos"),
            ]
        )
        self.tabs_table.setHorizontalHeaderLabels(
            [self.tr("Pestaña"), self.tr("Violaciones"), self.tr("Puntos")]
        )
        self.timetables_box.setTitle(self.tr("Horarios generados"))
        self.timetables_table.setHorizontalHeaderLabels(
            [
                self.tr("Activo"),
                self.tr("Id"),
                self.tr("Nombre"),
                self.tr("Evaluación"),
                self.tr("Sin colocar"),
                self.tr("Choques"),
            ]
        )
        set_texts(
            self.activate_button,
            self.tr("Activar"),
            self.tr("Hace activo el horario elegido: es el que ven Planificación y Horarios"),
        )
        set_texts(
            self.delete_button,
            self.tr("Borrar"),
            self.tr("Borra los horarios elegidos (se puede deshacer)"),
        )
        set_texts(
            self.compare_button,
            self.tr("Comparar"),
            self.tr("Elige dos horarios (Ctrl+clic) y compara sus cifras criterio a criterio"),
        )
        self.total_label.setToolTip(
            self.tr("Número de evaluación: cuanto más bajo, mejor es el horario")
        )
        self.compare_box.setTitle(self.tr("Comparación"))
        if self.view is not None:
            self._fill_breakdown(self.view)
        if self.compared is not None:
            self.compare(*self.compared)

    def _tab_label(self, tab: str) -> str:
        es, de = TAB_LABELS.get(tab, (tab, tab))
        return de if self.bridge.language == "de" else es

    def _criterion_label(self, criterion: str, fallback: str) -> str:
        textos = CRITERION_TEXTS.get(criterion)
        if textos is None:
            return fallback
        return textos[1] if self.bridge.language == "de" and textos[1] else textos[0]

    # --- refresco perezoso ----------------------------------------------------- #

    def _on_refreshed(self) -> None:
        if self.isVisible():
            self.refresh()
        else:
            self._stale = True

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def refresh(self) -> None:
        """Relee evaluación y horarios de la Fachada."""
        self._stale = False
        if not self.bridge.has_session:
            self.view = None
            self.summaries = ()
            self._fill_summary(None)
            self._fill_breakdown(None)
            self._fill_timetables()
            return
        s = self.bridge.session
        self.view = self.bridge.service.evaluation(s)
        self.summaries = self.bridge.service.timetables(s)
        self._fill_summary(self.view)
        self._fill_breakdown(self.view)
        self._fill_timetables()
        if self.compared is not None:
            ids = {t.id for t in self.summaries}
            if set(self.compared) <= ids:
                self.compare(*self.compared)
            else:
                self.compared = None
                self.compare_box.setVisible(False)

    def _fill_summary(self, view: EvaluationView | None) -> None:
        if view is None:
            for etiqueta in (
                self.total_label,
                self.unplaced_label,
                self.clashes_label,
                self.soft_label,
            ):
                etiqueta.setText("-")
            self.status_icon.setPixmap(icon("info").pixmap(STATUS_SIZE))
            self.status_icon.setProperty("state", "info")
            self.timetable_label.setText(self.tr("Sin horario activo"))
            self.status_text.setText(
                self.tr("Aún no hay horario: genera uno en la ventana Optimización.")
                if self.bridge.has_session
                else self.tr("Abre o crea un proyecto.")
            )
            return
        estado = status_of(view)
        self.status_icon.setPixmap(icon(estado).pixmap(STATUS_SIZE))
        self.status_icon.setProperty("state", estado)
        textos = {
            "error": self.tr(
                "Hay choques: un profesor, clase o aula está en dos sitios a la vez. "
                "Corrígelos con Reparar (Optimización) o en el Diagnóstico."
            ),
            "warning": self.tr(
                "No hay choques, pero quedan períodos sin colocar: colócalos en el "
                "Diálogo de planificación u optimiza de nuevo."
            ),
            "ok": self.tr("Horario completo y sin choques. Cuanto más bajo el número, mejor."),
        }
        self.status_text.setText(textos[estado])
        self.total_label.setText(fmt_int(view.total))
        self.unplaced_label.setText(fmt_int(view.unplaced_periods))
        self.clashes_label.setText(fmt_int(view.clashes))
        self.soft_label.setText(fmt_int(view.soft_points))
        nombre = next((t.name for t in self.summaries if t.id == view.timetable_id), "")
        self.timetable_label.setText(self.tr("Horario: {0}").format(nombre or view.timetable_id))

    def _fill_breakdown(self, view: EvaluationView | None) -> None:
        lineas = sorted(view.criteria, key=lambda c: -c.points) if view is not None else []
        self.criteria_table.setRowCount(len(lineas))
        por_pestana: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
        for fila, c in enumerate(lineas):
            valores: tuple[object, ...] = (
                self._criterion_label(c.criterion, c.label),
                self._tab_label(c.tab),
                c.slider,
                c.weight,
                c.violations,
                c.points,
            )
            for col, valor in enumerate(valores):
                item = _item(valor, align_right=col >= 2)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, c.criterion)
                self.criteria_table.setItem(fila, col, item)
            por_pestana[c.tab][0] += c.violations
            por_pestana[c.tab][1] += c.points
        subtotales = sorted(por_pestana.items(), key=lambda kv: -kv[1][1])
        self.tabs_table.setRowCount(len(subtotales))
        for fila, (tab, (violaciones, puntos)) in enumerate(subtotales):
            self.tabs_table.setItem(fila, 0, _item(self._tab_label(tab)))
            self.tabs_table.setItem(fila, 1, _item(violaciones, align_right=True))
            self.tabs_table.setItem(fila, 2, _item(puntos, align_right=True))

    def tab_subtotals(self) -> dict[str, int]:
        """Puntos por pestaña de Ponderación (lo que muestra la tabla de subtotales)."""
        totales: defaultdict[str, int] = defaultdict(int)
        if self.view is not None:
            for c in self.view.criteria:
                totales[c.tab] += c.points
        return dict(totales)

    def _fill_timetables(self) -> None:
        tabla = self.timetables_table
        tabla.setRowCount(len(self.summaries))
        negrita = QFont()
        negrita.setBold(True)
        for fila, t in enumerate(self.summaries):
            activo = _item("")
            activo.setCheckState(Qt.CheckState.Checked if t.active else Qt.CheckState.Unchecked)
            activo.setData(Qt.ItemDataRole.UserRole, t.id)
            tabla.setItem(fila, 0, activo)
            if t.active:
                activo.setIcon(icon("activate"))
                activo.setToolTip(self.tr("Horario activo"))
            for col, valor in enumerate((t.id, t.name, t.total, t.unplaced, t.clashes), start=1):
                item = _item(valor, align_right=col >= 3)
                if t.active:
                    item.setFont(negrita)
                tabla.setItem(fila, col, item)
        if self.bridge.has_session and not self.summaries:
            self.timetables_hint.show_message(
                self.tr("Aún no hay horarios generados: pulsa Iniciar en la ventana Optimización.")
            )
        else:
            self.timetables_hint.hide()
        self._update_buttons()

    # --- horarios generados ---------------------------------------------------- #

    def selected_ids(self) -> list[str]:
        filas = sorted({i.row() for i in self.timetables_table.selectedIndexes()})
        return [self.summaries[f].id for f in filas if f < len(self.summaries)]

    def select_ids(self, ids: list[str]) -> None:
        """Selecciona filas de la lista por id de horario."""
        tabla = self.timetables_table
        tabla.clearSelection()
        modo = tabla.selectionMode()
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for fila, t in enumerate(self.summaries):
            if t.id in ids:
                tabla.selectRow(fila)
        tabla.setSelectionMode(modo)

    def _update_buttons(self) -> None:
        n = len(self.selected_ids())
        libre = not self.bridge.busy
        self.activate_button.setEnabled(n == 1 and libre)
        self.delete_button.setEnabled(n >= 1 and libre)
        self.compare_button.setEnabled(n == 2)

    def activate(self, timetable_id: str) -> EditResult:
        """Hace activo un horario (el que ven Planificación y Horarios)."""
        s = self.bridge.session
        resultado = self.bridge.edit(
            lambda: self.bridge.service.set_active_timetable(s, timetable_id)
        )
        if resultado.ok:
            self.bridge.notify_changed(self.tr("Activar horario"))
            self.refresh()
        return resultado

    def activate_selected(self) -> EditResult | None:
        ids = self.selected_ids()
        return self.activate(ids[0]) if len(ids) == 1 else None

    def delete(self, timetable_id: str) -> EditResult:
        """Borra un horario generado (se puede deshacer)."""
        s = self.bridge.session
        resultado = self.bridge.edit(lambda: self.bridge.service.remove_timetable(s, timetable_id))
        if resultado.ok:
            self.refresh()
        return resultado

    def delete_selected(self) -> None:
        for ident in self.selected_ids():
            self.delete(ident)

    def compare_selected(self) -> bool:
        ids = self.selected_ids()
        if len(ids) != 2:
            return False
        self.compare(ids[0], ids[1])
        return True

    def compare(self, first: str, second: str) -> dict[str, int]:
        """Compara dos horarios: totales y diferencia por criterio (B - A).

        Devuelve `criterio -> diferencia de puntos` (con `total` para el número
        de evaluación).
        """
        s = self.bridge.session
        a = self.bridge.service.evaluation(s, first)
        b = self.bridge.service.evaluation(s, second)
        if a is None or b is None:
            return {}
        self.compared = (first, second)
        pa = {c.criterion: c for c in a.criteria}
        pb = {c.criterion: c for c in b.criteria}
        criterios = sorted(
            set(pa) | set(pb),
            key=lambda k: -abs((pb[k].points if k in pb else 0) - (pa[k].points if k in pa else 0)),
        )
        filas: list[tuple[str, int, int]] = [
            (self.tr("Número de evaluación"), a.total, b.total),
            (self.tr("Períodos sin colocar"), a.unplaced_periods, b.unplaced_periods),
            (self.tr("Choques"), a.clashes, b.clashes),
        ]
        deltas = {"total": b.total - a.total}
        for k in criterios:
            va = pa[k].points if k in pa else 0
            vb = pb[k].points if k in pb else 0
            etiqueta = (pa.get(k) or pb[k]).label
            filas.append((self._criterion_label(k, etiqueta), va, vb))
            deltas[k] = vb - va
        tabla = self.compare_table
        tabla.setHorizontalHeaderLabels([self.tr("Criterio"), first, second, self.tr("Diferencia")])
        tabla.setRowCount(len(filas))
        negrita = QFont()
        negrita.setBold(True)
        for fila, (nombre, va, vb) in enumerate(filas):
            diferencia = vb - va
            celdas = (
                _item(nombre),
                _item(va, align_right=True),
                _item(vb, align_right=True),
                _item(fmt_signed(diferencia), align_right=True),
            )
            if diferencia:
                celdas[3].setForeground(
                    Qt.GlobalColor.darkGreen if diferencia < 0 else Qt.GlobalColor.red
                )
            for col, item in enumerate(celdas):
                if fila < 3:
                    item.setFont(negrita)
                tabla.setItem(fila, col, item)
        self.compare_box.setVisible(True)
        return deltas


register(
    WindowSpec(
        key="evaluation",
        title="Evaluación",
        title_de="Bewertung",
        tab=RibbonTab.TIMETABLES,
        factory=lambda bridge: EvaluationWindow(bridge),
        order=2,
        icon="evaluation",
        tooltip="Cuánto de bueno es el horario (número de evaluación) y comparación de versiones.",
        tooltip_de="Wie gut der Stundenplan ist (Bewertungszahl) und Vergleich von Versionen.",
    )
)
