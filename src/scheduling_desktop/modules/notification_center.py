"""Módulo 14 · Notification Center: avisos de la sesión.

Recoge las notificaciones que emite el puente (proyecto guardado, importación
completada, versión creada, optimización terminada, errores) y las lista con hora
e icono por nivel.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..engine_bridge import EngineBridge

_ICON = {"info": "🔵", "success": "✅", "error": "⛔"}


class NotificationCenterModule(QWidget):
    """Panel de notificaciones de la aplicación."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge

        title = QLabel("Notificaciones")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        clear = QPushButton("Limpiar")
        clear.clicked.connect(self._clear)
        top = QHBoxLayout()
        top.addWidget(title, stretch=1)
        top.addWidget(clear)

        self._list = QListWidget()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._list, stretch=1)

        bridge.notification.connect(self._on_notification)

    def refresh(self) -> None:
        return None

    def _on_notification(self, level: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"{_ICON.get(level, '•')}  {stamp}  ·  {text}")
        self._list.insertItem(0, item)

    def _clear(self) -> None:
        self._list.clear()
