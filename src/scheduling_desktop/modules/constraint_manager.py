"""Módulo 5 · Reglas del horario: activar y ajustar las preferencias, en claro.

Lista las reglas con un **nombre sencillo**; cada una se activa/desactiva y —si es
una preferencia— se ajustan su **prioridad** y su **importancia** (peso). Todo se
enruta a la Fachada (``set_rule`` → ``PluginsConfig``); la UI no conoce ninguna
regla ni usa jerga técnica.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import ConstraintRow

from ..constraint_help import constraint_help
from ..engine_bridge import EngineBridge

_ID_ROLE = int(Qt.ItemDataRole.UserRole)
# Prioridad en palabras (antes "Tier"): qué se atiende primero al chocar reglas.
_TIERS = [("Alta", 1), ("Media", 2), ("Baja", 3)]


class ConstraintManagerModule(QWidget):
    """Editor del catálogo de restricciones (activación, tier, ponderación)."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._rows: dict[str, ConstraintRow] = {}
        self._current: str | None = None
        self._loading = False
        self._applying = False

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)

        self._title = QLabel("—")
        self._title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self._type = QLabel("")
        self._type.setStyleSheet("color: #475569; font-weight: 600;")
        self._help = QLabel("")
        self._help.setWordWrap(True)
        self._help.setStyleSheet(
            "background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px;"
            " padding: 10px; color: #1e3a8a;"
        )

        self._enabled = QCheckBox("Tener en cuenta esta regla")
        self._enabled.toggled.connect(self._apply)

        self._tier = QComboBox()
        for label, value in _TIERS:
            self._tier.addItem(label, value)
        self._tier.currentIndexChanged.connect(self._apply)

        self._weight = QSlider(Qt.Orientation.Horizontal)
        self._weight.setRange(1, 20)
        self._weight.valueChanged.connect(self._on_weight)
        self._weight_label = QLabel("1")

        weight_row = QHBoxLayout()
        weight_row.addWidget(self._weight, stretch=1)
        weight_row.addWidget(self._weight_label)

        self._weight_widget = QWidget()
        self._weight_widget.setLayout(weight_row)

        self._hard_note = QLabel("Es obligatoria: siempre se cumple, no se puede ajustar.")
        self._hard_note.setStyleSheet("color: #b45309; font-style: italic;")

        form = QFormLayout()
        form.addRow(self._enabled)
        self._tier_row_label = QLabel("Prioridad:")
        self._weight_row_label = QLabel("Importancia (1 a 20):")
        form.addRow(self._tier_row_label, self._tier)
        form.addRow(self._weight_row_label, self._weight_widget)
        form.addRow(self._hard_note)

        help_header = QLabel("¿Para qué sirve?")
        help_header.setStyleSheet("font-weight: 700; color: #1d4ed8;")
        detail = QVBoxLayout()
        detail.addWidget(self._title)
        detail.addWidget(self._type)
        detail.addWidget(help_header)
        detail.addWidget(self._help)
        detail.addLayout(form)
        detail.addStretch(1)
        detail_widget = QWidget()
        detail_widget.setLayout(detail)

        legend = QLabel(
            "Elige una regla de la lista para ver qué hace y ajustarla. "
            "● = activada, ○ = desactivada. Las obligatorias siempre se cumplen; "
            "las preferencias se intentan según su prioridad e importancia."
        )
        legend.setWordWrap(True)
        legend.setStyleSheet("color: #64748b;")

        columns = QHBoxLayout()
        columns.addWidget(self._list, stretch=1)
        columns.addWidget(detail_widget, stretch=2)

        layout = QVBoxLayout(self)
        layout.addWidget(legend)
        layout.addLayout(columns)

        self._set_detail_enabled(False)
        bridge.session_refreshed.connect(self.refresh)

    def refresh(self) -> None:
        # Se reconstruye la lista al abrir un proyecto, no en cada edición: una
        # reconstrucción reentrante durante _apply robaría la selección.
        if not self._bridge.has_session or self._applying:
            return
        self._loading = True
        rows = self._bridge.constraints_catalog()
        self._rows = {r.rule_id: r for r in rows}
        self._list.clear()
        for row in rows:
            estado = "●" if row.enabled else "○"
            item = QListWidgetItem(f"{estado}  {constraint_help(row.rule_id).title}")
            item.setData(_ID_ROLE, row.rule_id)
            item.setToolTip(constraint_help(row.rule_id).summary)
            self._list.addItem(item)
        self._loading = False
        # Reseleccionar la restricción que estaba abierta.
        target = self._current or (rows[0].rule_id if rows else None)
        if target is not None:
            self._select_rule(target)

    def _select_rule(self, rule_id: str) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(_ID_ROLE) == rule_id:
                self._list.setCurrentRow(i)
                return

    def _on_select(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if current is None:
            return
        rule_id = current.data(_ID_ROLE)
        if not isinstance(rule_id, str):
            return
        self._current = rule_id
        self._load(self._rows[rule_id])

    def _load(self, row: ConstraintRow) -> None:
        self._loading = True
        self._set_detail_enabled(True)
        help_text = constraint_help(row.rule_id)
        self._title.setText(help_text.title)
        if row.kind == "hard":
            self._type.setText("Tipo: obligatoria (siempre se cumple)")
        else:
            self._type.setText("Tipo: preferencia (se intenta cumplir)")
        self._help.setText(help_text.detail)
        self._enabled.setChecked(row.enabled)
        tier_index = self._tier.findData(row.tier if row.tier in (1, 2, 3) else row.default_tier)
        self._tier.setCurrentIndex(tier_index if tier_index >= 0 else 0)
        self._weight.setValue(row.weight)
        self._weight_label.setText(str(row.weight))
        # Las duras no tienen tier ni peso ponderable: se ocultan los controles y
        # se muestra una nota clara (en vez de un slider muerto).
        self._tier.setVisible(row.editable_tier)
        self._tier_row_label.setVisible(row.editable_tier)
        self._weight_widget.setVisible(row.editable_weight)
        self._weight_row_label.setVisible(row.editable_weight)
        self._hard_note.setVisible(not row.editable_weight)
        self._loading = False

    def _on_weight(self, value: int) -> None:
        self._weight_label.setText(str(value))
        self._apply()

    def _apply(self) -> None:
        if self._loading or self._current is None:
            return
        row = self._rows[self._current]
        enabled = self._enabled.isChecked()
        weight = self._weight.value() if row.editable_weight else None
        tier = self._tier.currentData() if row.editable_tier else None
        tier_value = tier if isinstance(tier, int) else None
        self._applying = True
        try:
            self._bridge.set_rule(self._current, enabled=enabled, weight=weight, tier=tier_value)
        finally:
            self._applying = False
        # Actualiza el estado local y el badge del ítem sin reconstruir la lista.
        self._rows[self._current] = replace(
            row,
            enabled=enabled,
            weight=weight if weight is not None else row.weight,
            tier=tier_value if tier_value is not None else row.tier,
        )
        self._update_badge(self._current)

    def _update_badge(self, rule_id: str) -> None:
        row = self._rows[rule_id]
        estado = "●" if row.enabled else "○"
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(_ID_ROLE) == rule_id:
                item.setText(f"{estado}  {constraint_help(rule_id).title}")
                return

    def _set_detail_enabled(self, enabled: bool) -> None:
        self._enabled.setEnabled(enabled)
        self._tier.setEnabled(enabled)
        self._weight.setEnabled(enabled)
