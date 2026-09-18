"""Idiomas es/de (sección 8 y decisión 3 del documento maestro).

El español es el idioma fuente. Las traducciones al alemán viven en
`translations/untis_desktop_de.ts` (fuente, versionada) y se compilan a `.qm`
con `pyside6-lrelease` (`scripts/i18n.py`). Si falta el `.qm`, la UI sigue en
español: el alemán nunca bloquea el arranque.

Las ventanas usan `QCoreApplication.translate(<contexto>, <texto>)` (o
`self.tr()` en `QObject`) y se re-traducen al recibir `language_changed`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator

TRANSLATIONS_DIR = Path(__file__).parent / "translations"
LANGUAGES = ("es", "de")

_installed: QTranslator | None = None


def qm_path(language: str) -> Path:
    return TRANSLATIONS_DIR / f"untis_desktop_{language}.qm"


def install_translator(app: QCoreApplication, language: str) -> bool:
    """Instala el traductor del idioma (o lo quita para español).

    Devuelve `True` si el idioma quedó activo.
    """
    global _installed
    if _installed is not None:
        app.removeTranslator(_installed)
        _installed = None
    if language == "es":
        QLocale.setDefault(QLocale(QLocale.Language.Spanish))
        return True
    ruta = qm_path(language)
    traductor = QTranslator()
    if not ruta.is_file() or not traductor.load(str(ruta)):
        return False
    app.installTranslator(traductor)
    _installed = traductor
    QLocale.setDefault(QLocale(QLocale.Language.German))
    return True


def tr(context: str, text: str) -> str:
    """Atajo de `QCoreApplication.translate` para código fuera de `QObject`."""
    return QCoreApplication.translate(context, text)
