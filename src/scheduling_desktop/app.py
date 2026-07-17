"""Punto de entrada de la app de escritorio: ``schedule-desktop``.

Crea el ``QApplication``, la ventana principal y (opcionalmente) abre el ``.bjs``
pasado como argumento. Toda la lógica vive en el motor; aquí solo se arranca la UI.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .engine_bridge import EngineBridge
from .main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    app = QApplication(args)
    app.setApplicationName("RealSchool")

    bridge = EngineBridge()
    window = MainWindow(bridge)
    window.show()

    if len(args) > 1:
        bridge.open_path(args[1])

    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
