"""Punto de entrada para el empaquetado a binario nativo (H11).

Los empaquetadores (PyInstaller/Nuitka) necesitan un script ejecutable, no un
``module:attr``. Este arranca la app Typer de la CLI.
"""

from __future__ import annotations

from scheduling_platform.cli.main import app

if __name__ == "__main__":
    app()
