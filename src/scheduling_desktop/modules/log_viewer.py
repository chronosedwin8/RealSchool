"""Módulo 13 · Log Viewer: telemetría y eventos en vivo.

Acumula los eventos del puente (progreso del solver, mensajes de estado,
resultados) con hora y permite filtrarlos. Es una consola de diagnóstico; no
toca el motor.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..engine_bridge import EngineBridge


class LogViewerModule(QWidget):
    """Registro filtrable de eventos de la sesión."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._lines: list[str] = []

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filtrar…")
        self._filter.textChanged.connect(self._render)
        clear = QPushButton("Limpiar")
        clear.clicked.connect(self._clear)
        top = QHBoxLayout()
        top.addWidget(QLabel("Registro de eventos"))
        top.addWidget(self._filter, stretch=1)
        top.addWidget(clear)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._log, stretch=1)

        bridge.status_message.connect(lambda text: self._add("estado", text))
        bridge.solve_progress.connect(
            lambda pct, stage: self._add("solver", f"{pct:3d}% · {stage}")
        )
        bridge.notification.connect(lambda level, text: self._add(level, text))

    def refresh(self) -> None:
        self._render()

    def _add(self, kind: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._lines.append(f"[{stamp}] {kind:<7} {text}")
        self._render()

    def _clear(self) -> None:
        self._lines.clear()
        self._render()

    def _render(self) -> None:
        needle = self._filter.text().lower()
        shown = [ln for ln in self._lines if needle in ln.lower()] if needle else self._lines
        self._log.setPlainText("\n".join(shown))
