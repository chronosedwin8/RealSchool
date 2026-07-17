"""Módulo 6 · Optimization Console: interfaz del solver (no contiene solver).

Elige backend y opciones, dispara Generar/Optimizar/Validar, muestra el progreso
en vivo (barra + consola) mientras el motor corre en un hilo aparte, y permite
Detener de forma cooperativa. Toda la ejecución pasa por el puente ``EngineBridge``.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import SolveOutcome

from ..engine_bridge import EngineBridge


class OptimizationConsoleModule(QWidget):
    """Panel de control del motor con progreso en vivo."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge

        self._solver = QComboBox()
        self._timeout = QDoubleSpinBox()
        self._timeout.setRange(1.0, 3600.0)
        self._timeout.setValue(30.0)
        self._timeout.setSuffix(" s")
        self._seed = QSpinBox()
        self._seed.setRange(0, 999_999)
        self._seed.setValue(42)

        form = QFormLayout()
        form.addRow("Solver:", self._solver)
        form.addRow("Tiempo máx.:", self._timeout)
        form.addRow("Semilla:", self._seed)

        self._btn_generate = QPushButton("Generar")
        self._btn_optimize = QPushButton("Optimizar")
        self._btn_validate = QPushButton("Validar")
        self._btn_stop = QPushButton("Detener")
        self._btn_stop.setEnabled(False)
        buttons = QHBoxLayout()
        for btn in (self._btn_generate, self._btn_optimize, self._btn_validate, self._btn_stop):
            buttons.addWidget(btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._stage = QLabel("Listo")
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self._progress)
        layout.addWidget(self._stage)
        layout.addWidget(self._log, stretch=1)

        self._btn_generate.clicked.connect(lambda: self._run(structural_only=True))
        self._btn_optimize.clicked.connect(lambda: self._run(structural_only=False))
        self._btn_validate.clicked.connect(self._validate)
        self._btn_stop.clicked.connect(self._bridge.cancel_optimize)

        bridge.session_opened.connect(self._populate_solvers)
        bridge.solve_progress.connect(self._on_progress)
        bridge.solve_finished.connect(self._on_finished)
        bridge.status_message.connect(self._append)

    def _populate_solvers(self) -> None:
        current = self._solver.currentText()
        self._solver.clear()
        self._solver.addItems(self._bridge.available_solvers())
        index = self._solver.findText(current)
        if index >= 0:
            self._solver.setCurrentIndex(index)

    def refresh(self) -> None:
        if self._bridge.has_session and self._solver.count() == 0:
            self._populate_solvers()

    # --- acciones ------------------------------------------------------- #
    def _run(self, *, structural_only: bool) -> None:
        if not self._bridge.has_session:
            return
        self._set_running(True)
        self._progress.setValue(0)
        verb = "Generando" if structural_only else "Optimizando"
        self._append(f"▶ {verb} con {self._solver.currentText()}…")
        self._bridge.start_optimize(
            solver=self._solver.currentText(),
            seed=self._seed.value(),
            timeout=self._timeout.value(),
            structural_only=structural_only,
        )

    def _validate(self) -> None:
        if not self._bridge.has_session:
            return
        report = self._bridge.validate()
        estado = "FACTIBLE" if report.feasible else "INFACTIBLE"
        self._append(
            f"■ Validación: {estado} ({len(report.errors)} errores, {len(report.warnings)} avisos)"
        )
        for item in report.items:
            marca = "✗" if item.severity == "error" else "⚠"
            self._append(f"   {marca} {item.message}")

    def _on_progress(self, percentage: int, stage: str) -> None:
        self._progress.setValue(percentage)
        self._stage.setText(f"{stage} ({percentage}%)")

    def _on_finished(self, outcome: SolveOutcome) -> None:
        self._set_running(False)
        if outcome.solved:
            self._progress.setValue(100)
            metrics = outcome.metrics or {}
            self._append(
                f"✓ {outcome.message} · calidad "
                f"{metrics.get('quality_score', '—')} · "
                f"violaciones {metrics.get('hard_violations', '—')}"
            )
        else:
            self._append(f"✗ {outcome.status}: {outcome.message}")

    def _set_running(self, running: bool) -> None:
        self._btn_generate.setEnabled(not running)
        self._btn_optimize.setEnabled(not running)
        self._btn_validate.setEnabled(not running)
        self._btn_stop.setEnabled(running)

    def _append(self, line: str) -> None:
        self._log.appendPlainText(line)
