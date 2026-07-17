"""Módulo 9 · Import / Export Center: entra y sale de datos del proyecto.

Importa exports XML de Untis (reutiliza el conversor del motor) y exporta el
proyecto a JSON. La UI solo orquesta diálogos de archivo y delega en la Fachada;
la conversión y la serialización viven en el motor.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import ConfigError

from ..engine_bridge import EngineBridge


def _card(title: str, subtitle: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(
        "QFrame#card { background: palette(base); border: 1px solid palette(mid);"
        " border-radius: 10px; padding: 6px; }"
    )
    box = QVBoxLayout(frame)
    head = QLabel(title)
    head.setStyleSheet("font-size: 15px; font-weight: 700;")
    sub = QLabel(subtitle)
    sub.setWordWrap(True)
    sub.setStyleSheet("color: #64748b;")
    box.addWidget(head)
    box.addWidget(sub)
    return frame, box


class ImportExportModule(QWidget):
    """Centro de importación y exportación."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge

        import_card, import_box = _card(
            "Importar de Untis (XML)",
            "Convierte un export de Untis en un proyecto RealSchool y lo abre.",
        )
        btn_import = QPushButton("Elegir archivo XML…")
        btn_import.clicked.connect(self._import_untis)
        import_box.addWidget(btn_import)

        export_card, export_box = _card(
            "Exportar proyecto (JSON)",
            "Guarda el problema, la solución y las métricas en un JSON legible "
            "(para respaldos o integraciones).",
        )
        self._btn_export = QPushButton("Exportar a JSON…")
        self._btn_export.clicked.connect(self._export_json)
        export_box.addWidget(self._btn_export)

        layout = QVBoxLayout(self)
        layout.addWidget(import_card)
        layout.addWidget(export_card)
        layout.addStretch(1)

        bridge.session_opened.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._btn_export.setEnabled(self._bridge.has_session)

    def _import_untis(self) -> None:
        xml, _ = QFileDialog.getOpenFileName(self, "Importar Untis", "", "Untis XML (*.xml)")
        if not xml:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Guardar proyecto como", f"{Path(xml).stem}.bjs", "Proyecto (*.bjs)"
        )
        if not dest:
            return
        try:
            self._bridge.import_untis(xml, dest)
        except (ConfigError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "No se pudo importar", str(exc))

    def _export_json(self) -> None:
        if not self._bridge.has_session:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Exportar a JSON", "proyecto.json", "JSON (*.json)"
        )
        if not dest:
            return
        try:
            self._bridge.export_json(dest)
        except OSError as exc:
            QMessageBox.warning(self, "No se pudo exportar", str(exc))
