"""Configuración de pruebas: Qt en modo *offscreen* para correr sin pantalla.

Se fija ``QT_QPA_PLATFORM=offscreen`` antes de importar PySide6 para que los
tests de la GUI (Fase 6) corran en CI/headless. El fixture ``qapp`` comparte una
única ``QApplication`` (Qt no admite dos) y está tipado para pasar mypy estricto.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app
