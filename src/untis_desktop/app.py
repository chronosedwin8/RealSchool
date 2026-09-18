"""Punto de entrada de la aplicación de escritorio (`schedule-desktop`)."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .i18n import install_translator
from .main_window import MainWindow
from .qt_bridge import FacadeBridge
from .theme import APP_QSS


def main(argv: list[str] | None = None) -> int:
    """Arranca RealSchool; un argumento opcional es el proyecto a abrir."""
    args = sys.argv if argv is None else argv
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(args)
    app.setOrganizationName("RealSchool")
    app.setApplicationName("RealSchool")
    app.setStyleSheet(APP_QSS)
    bridge = FacadeBridge()
    install_translator(app, bridge.language)
    bridge.language_changed.connect(lambda lang: install_translator(app, lang))
    ventana = MainWindow(bridge)
    ventana.show()
    if len(args) > 1:
        ventana.open_path(args[1])
    # Sin argumento no se crea nada: la página de Inicio ofrece crear un colegio
    # con el asistente, abrir uno, importar de Untis o probar el ejemplo.
    if os.environ.get("REALSCHOOL_SMOKE") == "1":
        # Prueba de humo del binario: arranca, abre y sale limpio.
        pestanas = ventana.ribbon.count()
        QTimer.singleShot(0, app.quit)
        codigo = app.exec()
        print(f"RealSchool smoke OK ({pestanas} pestañas en la cinta)")
        return codigo
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
