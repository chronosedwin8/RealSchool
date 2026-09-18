"""Configuración de pruebas: Qt en modo *offscreen* para correr sin pantalla.

Se fija ``QT_QPA_PLATFORM=offscreen`` antes de importar PySide6 para que los
tests de la GUI (Fase 6) corran en CI/headless. El fixture ``qapp`` comparte una
única ``QApplication`` (Qt no admite dos) y está tipado para pasar mypy estricto.
"""

from __future__ import annotations

import os
from pathlib import Path

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


# --------------------------------------------------------------------------- #
# Fixtures de Untis (refactorización R1+).
#
# - `tests/fixtures/real/*.xml`: exports reales del colegio. Tienen datos
#   personales, no se versionan (.gitignore) y los tests se saltan si faltan.
# - `tests/fixtures/untis_anon.xml`: el mismo export con nombres, correos y
#   textos seudonimizados por `scripts/anonymize_untis.py`. Sí se versiona, así
#   que la CI ejercita la estructura real (8 rejillas, 709 lecciones, acoples).
# --------------------------------------------------------------------------- #

FIXTURES = Path(__file__).parent / "fixtures"
REAL_DIR = FIXTURES / "real"
ANON_XML = FIXTURES / "untis_anon.xml"


def _real_xmls() -> list[Path]:
    return sorted(REAL_DIR.glob("*.xml")) if REAL_DIR.is_dir() else []


@pytest.fixture(scope="session")
def real_xml_paths() -> list[Path]:
    """Exports reales disponibles en local; salta el test si no hay ninguno."""
    paths = _real_xmls()
    if not paths:
        pytest.skip("No hay exports reales de Untis en tests/fixtures/real/")
    return paths


@pytest.fixture(scope="session")
def anon_xml_path() -> Path:
    """Export seudonimizado versionado: siempre disponible en la CI."""
    if not ANON_XML.is_file():
        pytest.skip("Falta tests/fixtures/untis_anon.xml (scripts/anonymize_untis.py)")
    return ANON_XML
