"""Ventana Optimización: datos de control, progreso en vivo y resultado.

Replica el ciclo de Untis (sección 3 y 7 del documento maestro): el usuario
elige estrategia A (rápida, para detectar errores de datos), B (compleja), D
(colocación por porcentaje), E (nocturna) o Reparar (solo pulido CP-SAT del
horario actual), lanza y mira evolucionar el número de evaluación. Es la única
ventana que sigue activa mientras se optimiza (clave `optimization`), porque
aquí está el botón Detener.

Una franja arriba explica el orden de trabajo (A para encontrar errores de
datos, B para el horario de trabajo, E de noche). Iniciar se desactiva, con el
motivo al lado, si no hay lecciones o si el diagnóstico de datos tiene errores.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import OptimizeOutcome, OptimizeProgress, OptimizeRequest

from ..icons import icon, icon_size
from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import fmt_int
from ..widgets.uikit import Banner, set_texts

#: Icono de cada estrategia.
STRATEGY_ICONS: dict[str, str] = {
    "A": "launch",
    "B": "optimize",
    "D": "shuffle",
    "E": "afternoon",
    "repair": "repair",
}


#: Estrategias en el orden del diálogo y su tiempo límite por defecto (s).
STRATEGIES: tuple[str, ...] = ("A", "B", "D", "E", "repair")
DEFAULT_LIMITS: dict[str, float] = {"A": 60.0, "B": 600.0, "D": 600.0, "E": 1800.0, "repair": 30.0}


class BestChart(QWidget):
    """Gráfico mínimo del mejor número de evaluación a lo largo del tiempo.

    Pintado a mano (sin QtCharts): basta una línea escalonada y es barato
    repintarlo con cada evento de progreso.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.points: list[tuple[float, int]] = []
        self.setMinimumHeight(90)

    def sizeHint(self) -> QSize:
        return QSize(360, 120)

    def clear(self) -> None:
        self.points.clear()
        self.update()

    def add(self, elapsed: float, best: int) -> None:
        if self.points and self.points[-1] == (elapsed, best):
            return
        self.points.append((elapsed, best))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        marco = self.rect().adjusted(4, 4, -4, -4)
        pintor.fillRect(marco, QColor("#ffffff"))
        pintor.setPen(QPen(QColor("#d1d5db")))
        pintor.drawRect(marco)
        if len(self.points) >= 1:
            t_max = max(self.points[-1][0], 1e-6)
            valores = [b for _, b in self.points]
            v_min, v_max = min(valores), max(valores)
            rango = max(v_max - v_min, 1)
            poligono = QPolygonF()
            anterior_y: float | None = None
            for t, b in self.points:
                x = marco.left() + (t / t_max) * marco.width()
                y = marco.bottom() - ((b - v_min) / rango) * (marco.height() - 14) - 4
                if anterior_y is not None:
                    poligono.append(QPointF(x, anterior_y))
                poligono.append(QPointF(x, y))
                anterior_y = y
            pintor.setPen(QPen(QColor("#2563eb"), 2))
            pintor.drawPolyline(poligono)
            pintor.setPen(QPen(QColor("#374151")))
            pintor.drawText(marco.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignTop, fmt_int(v_max))
            pintor.drawText(
                marco.adjusted(4, 2, -4, -2),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
                fmt_int(valores[-1]),
            )
        pintor.end()


class OptimizationWindow(QWidget):
    """Datos de control de la optimización y su progreso."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self._limits = dict(DEFAULT_LIMITS)
        self._strategy = "A"
        self.outcome: OptimizeOutcome | None = None
        self._ready: tuple[object, str] | None = None
        """`(proyecto, motivo)` de la última comprobación de Iniciar."""

        self.intro = Banner("tip")

        # --- estrategia ----------------------------------------------------- #
        self.strategy_box = QGroupBox()
        rejilla = QGridLayout(self.strategy_box)
        self.strategy_group = QButtonGroup(self)
        self.strategy_radios: dict[str, QRadioButton] = {}
        self.strategy_help: dict[str, QLabel] = {}
        for fila, clave in enumerate(STRATEGIES):
            radio = QRadioButton()
            radio.setIcon(icon(STRATEGY_ICONS[clave]))
            radio.setIconSize(icon_size("button"))
            ayuda = QLabel()
            ayuda.setWordWrap(True)
            ayuda.setStyleSheet("color: #4b5563;")
            self.strategy_group.addButton(radio, fila)
            self.strategy_radios[clave] = radio
            self.strategy_help[clave] = ayuda
            rejilla.addWidget(radio, fila, 0)
            rejilla.addWidget(ayuda, fila, 1)
        rejilla.setColumnStretch(1, 1)
        self.strategy_radios["A"].setChecked(True)
        self.strategy_group.idToggled.connect(self._on_strategy_toggled)

        # --- parámetros ------------------------------------------------------ #
        self.params_box = QGroupBox()
        formulario = QFormLayout(self.params_box)
        self.time_limit = QDoubleSpinBox()
        self.time_limit.setRange(1.0, 7 * 24 * 3600.0)
        self.time_limit.setDecimals(0)
        self.time_limit.setSuffix(" s")
        self.time_limit.setValue(self._limits["A"])
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_000_000_000)
        self.placement = QSpinBox()
        self.placement.setRange(1, 100)
        self.placement.setValue(60)
        self.placement.setSuffix(" %")
        self.optimize_teachers = QCheckBox()
        self.optimize_teachers.setIcon(icon("teachers"))
        self.polish = QCheckBox()
        self.polish.setIcon(icon("wizard"))
        self.polish.setChecked(True)
        self._lbl_limit = QLabel()
        self._lbl_seed = QLabel()
        self._lbl_placement = QLabel()
        formulario.addRow(self._lbl_limit, self.time_limit)
        formulario.addRow(self._lbl_seed, self.seed)
        formulario.addRow(self._lbl_placement, self.placement)
        formulario.addRow(self.optimize_teachers)
        formulario.addRow(self.polish)

        # --- órdenes ---------------------------------------------------------- #
        self.start_button = QPushButton(icon("start"), "")
        self.start_button.setIconSize(icon_size("ribbon"))
        self.start_button.setStyleSheet(
            "QPushButton { background: #dcfce7; border: 1px solid #16a34a; border-radius: 4px;"
            " padding: 6px 14px; font-weight: bold; color: #14532d; }"
            "QPushButton:disabled { background: #f3f4f6; border-color: #d1d5db; color: #9ca3af; }"
        )
        self.start_button.clicked.connect(lambda _c=False: self.start())
        self.stop_button = QPushButton(icon("stop"), "")
        self.stop_button.setIconSize(icon_size("ribbon"))
        self.stop_button.setStyleSheet(
            "QPushButton { background: #fee2e2; border: 1px solid #dc2626; border-radius: 4px;"
            " padding: 6px 14px; font-weight: bold; color: #7f1d1d; }"
            "QPushButton:disabled { background: #f3f4f6; border-color: #d1d5db; color: #9ca3af; }"
        )
        self.stop_button.clicked.connect(lambda _c=False: self.stop())
        self.stop_button.setEnabled(False)
        self.reason = Banner("warning")
        self.reason.hide()
        ordenes = QHBoxLayout()
        ordenes.addWidget(self.start_button)
        ordenes.addWidget(self.stop_button)
        ordenes.addStretch(1)

        # --- progreso ---------------------------------------------------------- #
        self.progress_box = QGroupBox()
        progreso = QFormLayout(self.progress_box)
        self.phase_label = QLabel("-")
        self.iteration_label = QLabel("-")
        self.current_label = QLabel("-")
        self.best_label = QLabel("-")
        fuerte = QFont()
        fuerte.setPointSize(14)
        fuerte.setBold(True)
        self.best_label.setFont(fuerte)
        self.unplaced_label = QLabel("-")
        self.elapsed_label = QLabel("-")
        self._progress_names = [QLabel() for _ in range(6)]
        for nombre, valor in zip(
            self._progress_names,
            (
                self.phase_label,
                self.iteration_label,
                self.current_label,
                self.best_label,
                self.unplaced_label,
                self.elapsed_label,
            ),
            strict=True,
        ):
            progreso.addRow(nombre, valor)
        self.chart = BestChart()
        progreso.addRow(self.chart)

        # --- resultado -------------------------------------------------------- #
        self.result_box = QGroupBox()
        resultado = QVBoxLayout(self.result_box)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.open_evaluation = QPushButton(icon("evaluation"), "")
        self.open_evaluation.clicked.connect(lambda _c=False: self._open_window("evaluation"))
        self.open_diagnosis = QPushButton(icon("diagnosis"), "")
        self.open_diagnosis.clicked.connect(lambda _c=False: self._open_window("diagnosis"))
        enlaces = QHBoxLayout()
        enlaces.addWidget(self.open_evaluation)
        enlaces.addWidget(self.open_diagnosis)
        enlaces.addStretch(1)
        resultado.addWidget(self.result_label)
        resultado.addWidget(self.log, 1)
        resultado.addLayout(enlaces)

        izquierda = QVBoxLayout()
        izquierda.addWidget(self.strategy_box)
        izquierda.addWidget(self.params_box)
        izquierda.addLayout(ordenes)
        izquierda.addWidget(self.reason)
        izquierda.addStretch(1)
        derecha = QVBoxLayout()
        derecha.addWidget(self.progress_box)
        derecha.addWidget(self.result_box, 1)
        columnas = QHBoxLayout()
        columnas.addLayout(izquierda, 1)
        columnas.addLayout(derecha, 1)
        principal = QVBoxLayout(self)
        principal.addWidget(self.intro)
        principal.addLayout(columnas, 1)

        bridge.optimize_progress.connect(self._on_progress)
        bridge.optimize_finished.connect(self._on_finished)
        bridge.busy_changed.connect(self._on_busy)
        bridge.project_opened.connect(self._update_enabled)
        bridge.refreshed.connect(self._update_enabled)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()
        self._update_placement()
        self._update_enabled()

    # --- textos ------------------------------------------------------------- #

    def _retranslate(self) -> None:
        self.strategy_box.setTitle(self.tr("Estrategia"))
        nombres = {
            "A": self.tr("A - rápida"),
            "B": self.tr("B - compleja"),
            "D": self.tr("D - colocación %"),
            "E": self.tr("E - nocturna"),
            "repair": self.tr("Reparar"),
        }
        ayudas = {
            "A": self.tr("Colocación y pocos intercambios: sirve para detectar errores de datos."),
            "B": self.tr("Varios reinicios y pulido: el horario de trabajo."),
            "D": self.tr("Coloca solo el % más difícil y deja el resto al pulido CP-SAT."),
            "E": self.tr("B repetida muchas veces con límite alto: la versión final."),
            "repair": self.tr("Corrige choques del horario actual con el mínimo cambio."),
        }
        for clave in STRATEGIES:
            self.strategy_radios[clave].setText(nombres[clave])
            self.strategy_radios[clave].setToolTip(ayudas[clave])
            self.strategy_help[clave].setText(ayudas[clave])
        self.intro.setText(
            self.tr(
                "Cómo trabajar: primero corre A (rápida) para detectar errores de datos y "
                "corrígelos en el Diagnóstico; luego B para el horario de trabajo; E de noche "
                "para la versión final. Reparar solo corrige choques del horario actual."
            )
        )
        self.params_box.setTitle(self.tr("Datos de control"))
        self._lbl_limit.setText(self.tr("Tiempo máximo"))
        self._lbl_seed.setText(self.tr("Semilla"))
        self._lbl_placement.setText(self.tr("Colocación"))
        self.time_limit.setToolTip(self.tr("La optimización se para sola al llegar a este tiempo"))
        self.seed.setToolTip(
            self.tr("Cambia la semilla para obtener otro horario distinto con los mismos datos")
        )
        self.placement.setToolTip(
            self.tr("Solo estrategia D: qué parte de las lecciones coloca antes del pulido")
        )
        self.optimize_teachers.setText(self.tr("Optimización de profesores"))
        self.optimize_teachers.setToolTip(
            self.tr("Deja que la optimización elija profesor en las líneas que no lo tienen")
        )
        self.polish.setText(self.tr("Pulido CP-SAT"))
        self.polish.setToolTip(
            self.tr("Al final, un repaso exacto que suele bajar algo más el número de evaluación")
        )
        set_texts(
            self.start_button,
            self.tr("Iniciar"),
            self.tr("Genera un horario nuevo con la estrategia elegida (el actual se conserva)"),
        )
        set_texts(
            self.stop_button,
            self.tr("Detener"),
            self.tr("Para la optimización y se queda con el mejor horario encontrado hasta ahora"),
        )
        self.progress_box.setTitle(self.tr("Progreso"))
        for etiqueta, texto in zip(
            self._progress_names,
            (
                self.tr("Fase"),
                self.tr("Iteración"),
                self.tr("Evaluación actual"),
                self.tr("Mejor evaluación"),
                self.tr("Sin colocar"),
                self.tr("Tiempo"),
            ),
            strict=True,
        ):
            etiqueta.setText(texto)
        self.result_box.setTitle(self.tr("Resultado"))
        set_texts(
            self.open_evaluation,
            self.tr("Abrir Evaluación"),
            self.tr("Muestra el número de evaluación y compara los horarios generados"),
        )
        set_texts(
            self.open_diagnosis,
            self.tr("Abrir Diagnóstico"),
            self.tr("Muestra los problemas del horario y de los datos, con salto a cada uno"),
        )
        self._ready = None
        self._update_enabled()

    # --- datos de control ------------------------------------------------------ #

    @property
    def strategy(self) -> str:
        return self._strategy

    def set_strategy(self, strategy: str) -> None:
        """Elige una estrategia (como pulsar su botón de radio)."""
        self.strategy_radios[strategy].setChecked(True)

    def _on_strategy_toggled(self, button_id: int, checked: bool) -> None:
        if not checked:
            return
        self._limits[self._strategy] = self.time_limit.value()
        self._strategy = STRATEGIES[button_id]
        self.time_limit.setValue(self._limits[self._strategy])
        self._update_placement()

    def _update_placement(self) -> None:
        self.placement.setEnabled(self._strategy == "D")

    def request(self) -> OptimizeRequest:
        """Los datos de control tal como están en la ventana."""
        return OptimizeRequest(
            strategy=self._strategy,
            time_limit=self.time_limit.value(),
            seed=self.seed.value(),
            placement_share=self.placement.value() / 100.0 if self._strategy == "D" else 1.0,
            optimize_teachers=self.optimize_teachers.isChecked(),
            polish=self.polish.isChecked(),
        )

    # --- órdenes -------------------------------------------------------------- #

    def start(self) -> bool:
        """Lanza la optimización en segundo plano (si los datos lo permiten)."""
        if not self.bridge.has_session or self.blocking_reason():
            self._update_enabled()
            return False
        return self.bridge.start_optimize(self.request())

    def blocking_reason(self) -> str:
        """Por qué no se puede optimizar ahora ("" si se puede)."""
        if not self.bridge.has_session:
            return self.tr("Abre o crea un proyecto para poder optimizar.")
        proyecto = self.bridge.session.project
        if self._ready is not None and self._ready[0] is proyecto:
            return self._ready[1]
        svc, s = self.bridge.service, self.bridge.session
        motivo = ""
        if not any(not le.ignore for le in svc.lessons(s)):
            motivo = self.tr(
                "No hay lecciones que colocar: créalas en la ventana Lecciones "
                "(materia, profesor, clases y períodos)."
            )
        else:
            errores = [
                i
                for i in svc.data_diagnosis(s).items
                if i.branch == "datos" and i.severity == "error"
            ]
            if errores:
                motivo = self.tr(
                    "Hay {0} error(es) en los datos (p. ej. «{1}»). Corrígelos desde el "
                    "Diagnóstico antes de optimizar."
                ).format(len(errores), errores[0].message)
        self._ready = (proyecto, motivo)
        return motivo

    def stop(self) -> None:
        self.bridge.cancel_optimize()
        self.phase_label.setText(self.tr("Deteniendo..."))

    def _open_window(self, key: str) -> None:
        principal = self.window()
        abrir = getattr(principal, "show_window", None)
        if callable(abrir):
            abrir(key)

    # --- eventos del puente --------------------------------------------------- #

    def _update_enabled(self) -> None:
        ocupado = self.bridge.busy
        motivo = "" if ocupado else self.blocking_reason()
        self.start_button.setEnabled(self.bridge.has_session and not ocupado and not motivo)
        self.reason.show_message(motivo, "warning")
        self.stop_button.setEnabled(ocupado)
        for caja in (self.strategy_box, self.params_box):
            caja.setEnabled(not ocupado)

    def _on_busy(self, busy: bool) -> None:
        if busy:
            self.chart.clear()
            self.outcome = None
            self.result_label.clear()
            self.log.clear()
            for etiqueta in (
                self.iteration_label,
                self.current_label,
                self.best_label,
                self.unplaced_label,
                self.elapsed_label,
            ):
                etiqueta.setText("-")
            self.phase_label.setText(self.tr("Iniciando..."))
        self._update_enabled()

    def _on_progress(self, event: object) -> None:
        if not isinstance(event, OptimizeProgress):
            return
        self.phase_label.setText(event.phase)
        self.iteration_label.setText(fmt_int(event.iteration))
        self.current_label.setText(fmt_int(event.current))
        self.best_label.setText(fmt_int(event.best))
        self.unplaced_label.setText(fmt_int(event.unplaced))
        self.elapsed_label.setText(f"{event.elapsed:.1f} s")
        self.chart.add(event.elapsed, event.best)

    def _on_finished(self, outcome: object) -> None:
        if not isinstance(outcome, OptimizeOutcome):
            return
        self.outcome = outcome
        estados = {
            "solved": self.tr("Terminado"),
            "cancelled": self.tr("Detenido"),
            "error": self.tr("Error"),
        }
        self.phase_label.setText(estados.get(outcome.status, outcome.status))
        self.result_label.setText(outcome.message)
        self.result_label.setStyleSheet("" if outcome.ok else "color: #b91c1c;")
        if outcome.evaluation is not None:
            self.best_label.setText(fmt_int(outcome.evaluation.total))
            self.unplaced_label.setText(fmt_int(outcome.evaluation.unplaced_periods))
            self.chart.add(outcome.elapsed, outcome.evaluation.total)
        self.elapsed_label.setText(f"{outcome.elapsed:.1f} s")
        self.log.setPlainText("\n".join(outcome.log))
        self._update_enabled()


register(
    WindowSpec(
        key="optimization",
        title="Optimización",
        title_de="Optimierung",
        tab=RibbonTab.TIMETABLES,
        factory=lambda bridge: OptimizationWindow(bridge),
        order=1,
        icon="optimize",
        tooltip="Genera el horario automáticamente y muestra cómo mejora mientras trabaja.",
        tooltip_de="Erzeugt den Stundenplan automatisch und zeigt, wie er sich dabei verbessert.",
    )
)
