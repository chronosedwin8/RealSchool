"""Ventana Datos del colegio: nombre, curso, encabezados e idioma de la interfaz.

Los campos salen de la Fachada (`school_info` / `SCHOOL_FIELDS`) y se editan con
`set_school_field`; una fecha mal escrita deja el campo en rojo con el motivo.
El selector de idioma cambia toda la interfaz (es/de) al instante.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from scheduling_platform.application import EditResult

from ..qt_bridge import FacadeBridge
from ..registry import RibbonTab, WindowSpec, register
from ..theme import ERROR_COLOR

#: Idiomas de la interfaz: `(código, nombre propio)`.
LANGUAGES: tuple[tuple[str, str], ...] = (("es", "Español"), ("de", "Deutsch"))


class SettingsWindow(QWidget):
    """Datos del colegio y ajustes de la interfaz."""

    def __init__(self, bridge: FacadeBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self.fields: dict[str, QLineEdit] = {}
        self.labels: dict[str, QLabel] = {}
        self._errors: dict[str, str] = {}

        self.school_box = QGroupBox()
        self.form = QFormLayout(self.school_box)
        for campo in bridge.service.SCHOOL_FIELDS:
            etiqueta = QLabel()
            editor = QLineEdit()
            editor.editingFinished.connect(lambda c=campo: self._on_edited(c))
            self.form.addRow(etiqueta, editor)
            self.fields[campo] = editor
            self.labels[campo] = etiqueta

        self.ui_box = QGroupBox()
        ui = QFormLayout(self.ui_box)
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        for codigo, nombre in LANGUAGES:
            self.language_combo.addItem(nombre, codigo)
        self.language_combo.currentIndexChanged.connect(self._on_language)
        ui.addRow(self.language_label, self.language_combo)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet(f"background: {ERROR_COLOR}; padding: 3px;")
        self.message.hide()

        raiz = QVBoxLayout(self)
        raiz.addWidget(self.school_box)
        raiz.addWidget(self.ui_box)
        raiz.addWidget(self.message)
        raiz.addStretch(1)

        bridge.refreshed.connect(self.refresh)
        bridge.language_changed.connect(lambda _lang: self._retranslate())
        self._retranslate()
        self.refresh()

    def refresh(self) -> None:
        valores = (
            dict(self.bridge.service.school_info(self.bridge.session))
            if self.bridge.has_session
            else {}
        )
        for campo, editor in self.fields.items():
            if campo not in self._errors:
                editor.setText(valores.get(campo, ""))
            editor.setEnabled(self.bridge.has_session)
            self._paint(campo)

    def _paint(self, field: str) -> None:
        editor = self.fields[field]
        error = self._errors.get(field, "")
        editor.setStyleSheet(f"background: {ERROR_COLOR};" if error else "")
        editor.setToolTip(error)

    def _on_edited(self, field: str) -> None:
        self.set_field(field, self.fields[field].text())

    def set_field(self, field: str, value: str) -> EditResult:
        """Edita un dato del colegio; en rojo si la Fachada lo rechaza."""
        if not self.bridge.has_session:
            return EditResult.failure(self.tr("No hay proyecto abierto"))
        actuales = dict(self.bridge.service.school_info(self.bridge.session))
        if actuales.get(field) == value.strip() and field not in self._errors:
            return EditResult.success()
        self.fields[field].setText(value)
        svc = self.bridge.service
        resultado = self.bridge.edit(
            lambda: svc.set_school_field(self.bridge.session, field, value)
        )
        if resultado.ok:
            self._errors.pop(field, None)
        else:
            self._errors[field] = resultado.message
        self.message.setText("" if resultado.ok else resultado.message)
        self.message.setVisible(not resultado.ok)
        self._paint(field)
        return resultado

    def error_at(self, field: str) -> str:
        return self._errors.get(field, "")

    def _on_language(self, _index: int) -> None:
        codigo = str(self.language_combo.currentData() or "es")
        self.bridge.set_language(codigo)

    def _retranslate(self) -> None:
        de = self.bridge.language == "de"
        for campo, (es, aleman) in self.bridge.service.SCHOOL_FIELDS.items():
            self.labels[campo].setText(aleman if de else es)
        self.school_box.setTitle(self.tr("Datos del colegio"))
        self.ui_box.setTitle(self.tr("Interfaz"))
        self.language_label.setText(self.tr("Idioma"))
        indice = self.language_combo.findData(self.bridge.language)
        if indice >= 0 and indice != self.language_combo.currentIndex():
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(indice)
            self.language_combo.blockSignals(False)


register(
    WindowSpec(
        key="settings",
        title="Datos del colegio",
        title_de="Schuldaten",
        tab=RibbonTab.HOME,
        factory=SettingsWindow,
        order=10,
    )
)
