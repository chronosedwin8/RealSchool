"""Punto de entrada del binario de escritorio (R5).

PyInstaller necesita un script, no un ``module:attr``. Con la variable de entorno
``REALSCHOOL_SMOKE=1`` la aplicación construye la ventana principal, abre el
proyecto indicado (si lo hay) y sale: así la CI comprueba que el binario
congelado arranca de verdad, sin pantalla (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

from untis_desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
