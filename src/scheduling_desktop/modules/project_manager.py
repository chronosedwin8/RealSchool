"""Módulo 10 · Project Manager: ciclo de vida del proyecto y versiones.

Abrir / Guardar / Guardar como, y **versiones (snapshots)**: copias con fecha del
``.bjs`` que se pueden restaurar. La UI delega en la Fachada (guardado atómico +
copia de snapshots); no manipula archivos por su cuenta salvo elegir rutas.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..engine_bridge import EngineBridge

_PATH_ROLE = int(Qt.ItemDataRole.UserRole)
_FILTER = "Proyecto RealSchool (*.bjs)"


class ProjectManagerModule(QWidget):
    """Gestión del proyecto: guardar, guardar como y versiones."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge

        self._info = QLabel("Sin proyecto abierto")
        self._info.setStyleSheet("font-size: 15px; font-weight: 700;")

        btn_open = QPushButton("Abrir…")
        btn_open.clicked.connect(self._open)
        self._btn_save = QPushButton("Guardar")
        self._btn_save.clicked.connect(self._save)
        self._btn_save_as = QPushButton("Guardar como…")
        self._btn_save_as.clicked.connect(self._save_as)
        self._btn_snapshot = QPushButton("Crear versión")
        self._btn_snapshot.clicked.connect(self._snapshot)
        actions = QHBoxLayout()
        for btn in (btn_open, self._btn_save, self._btn_save_as, self._btn_snapshot):
            actions.addWidget(btn)
        actions.addStretch(1)

        self._snapshots = QListWidget()
        self._snapshots.itemActivated.connect(self._restore)
        self._snapshots.itemDoubleClicked.connect(self._restore)

        layout = QVBoxLayout(self)
        layout.addWidget(self._info)
        layout.addLayout(actions)
        layout.addWidget(QLabel("Versiones guardadas (doble-clic para restaurar):"))
        layout.addWidget(self._snapshots, stretch=1)

        bridge.session_opened.connect(self.refresh)
        bridge.dirty_changed.connect(lambda _dirty: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        has = self._bridge.has_session
        for btn in (self._btn_save, self._btn_save_as, self._btn_snapshot):
            btn.setEnabled(has)
        if not has:
            self._info.setText("Sin proyecto abierto")
            self._snapshots.clear()
            return
        path = self._bridge.path
        name = path.name if path is not None else "sin título"
        self._info.setText(f"Proyecto: {name}")
        self._reload_snapshots()

    def _reload_snapshots(self) -> None:
        self._snapshots.clear()
        for snap in self._bridge.list_snapshots():
            item = QListWidgetItem(snap.stem)
            item.setData(_PATH_ROLE, str(snap))
            self._snapshots.addItem(item)

    # --- acciones ------------------------------------------------------- #
    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", "", _FILTER)
        if path:
            self._bridge.open_path(path)

    def _save(self) -> None:
        if self._bridge.path is None:
            self._save_as()
        else:
            self._bridge.save()

    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Guardar como", "", _FILTER)
        if path:
            self._bridge.save(path)
            self.refresh()

    def _snapshot(self) -> None:
        if self._bridge.path is None:
            self._save_as()
            if self._bridge.path is None:
                return
        self._bridge.snapshot()
        self._reload_snapshots()

    def _restore(self, item: QListWidgetItem) -> None:
        path = item.data(_PATH_ROLE)
        if not isinstance(path, str):
            return
        confirm = QMessageBox.question(
            self,
            "Restaurar versión",
            f"¿Abrir la versión {Path(path).stem}? Los cambios sin guardar se perderán.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._bridge.open_path(path)
