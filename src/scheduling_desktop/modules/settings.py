"""Módulo 11 · Settings: configuración del motor del proyecto.

Solver por defecto, hilos, tiempo máximo y semilla. Se guarda en el proyecto vía
la Fachada (``update_engine_settings``); la UI no conoce los valores válidos: el
motor los valida y rechaza los incorrectos.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import ConfigError

from ..engine_bridge import EngineBridge


class SettingsModule(QWidget):
    """Configuración global del motor por proyecto."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge

        self._solver = QComboBox()
        self._threads = QSpinBox()
        self._threads.setRange(1, 64)
        self._time = QDoubleSpinBox()
        self._time.setRange(1.0, 36000.0)
        self._time.setSuffix(" s")
        self._seed = QSpinBox()
        self._seed.setRange(0, 999_999)

        form = QFormLayout()
        form.addRow("Solver por defecto:", self._solver)
        form.addRow("Hilos:", self._threads)
        form.addRow("Tiempo máximo:", self._time)
        form.addRow("Semilla:", self._seed)

        self._save = QPushButton("Guardar configuración")
        self._save.clicked.connect(self._apply)
        self._status = QLabel("")
        self._status.setStyleSheet("color: #64748b;")

        title = QLabel("Configuración del motor")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addWidget(self._save)
        layout.addWidget(self._status)
        layout.addStretch(1)

        bridge.session_opened.connect(self.refresh)

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        cfg = self._bridge.engine_settings()
        self._solver.clear()
        self._solver.addItems(self._bridge.available_solvers())
        index = self._solver.findText(cfg.default_solver)
        self._solver.setCurrentIndex(index if index >= 0 else 0)
        self._threads.setValue(cfg.threads)
        self._time.setValue(cfg.max_time_seconds)
        self._seed.setValue(cfg.random_seed)

    def _apply(self) -> None:
        if not self._bridge.has_session:
            return
        try:
            self._bridge.update_engine_settings(
                default_solver=self._solver.currentText(),
                threads=self._threads.value(),
                max_time_seconds=self._time.value(),
                random_seed=self._seed.value(),
            )
            self._status.setText("Configuración guardada en el proyecto.")
        except ConfigError as exc:
            self._status.setText(f"No válida: {exc}")
