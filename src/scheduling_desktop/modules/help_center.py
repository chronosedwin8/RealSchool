"""Módulo 15 · Help Center: ayuda integrada.

Guía rápida de los módulos y atajos, y un acceso a la **documentación offline**
del SDK (Fase 4) si está construida (``site/index.html``). No depende de un
navegador embebido: abre la doc en el navegador del sistema.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QPushButton, QTextBrowser, QVBoxLayout, QWidget

from ..engine_bridge import EngineBridge

_HELP_HTML = """
<h2>RealSchool — Ayuda rápida</h2>
<p>Organiza el horario en módulos, como Untis. Todo el cálculo lo hace el motor;
la interfaz solo presenta y edita.</p>
<h3>Módulos</h3>
<ul>
<li><b>Tablero</b>: resumen del proyecto (conteos y calidad).</li>
<li><b>Datos</b>: docentes, aulas, grupos y materias; edición básica.</li>
<li><b>Horario</b>: rejilla semanal. Arrastra una clase para moverla
    (<b>verde</b> = se puede, <b>rojo</b> = ocupado). <i>Deshacer</i> revierte.</li>
<li><b>Restricciones</b>: activa reglas y ajusta su <b>ponderación</b>; cada una
    trae una explicación de para qué sirve.</li>
<li><b>Validación</b>: lista los problemas y salta al elemento.</li>
<li><b>Informes</b>: carga docente, uso de aulas, calidad; exporta a CSV.</li>
<li><b>Importar/Exportar</b>: importa de Untis (XML) y exporta a JSON.</li>
<li><b>Proyecto</b>: guardar, guardar como y <b>versiones</b> restaurables.</li>
<li><b>Optimización</b>: elige solver y opciones; Generar/Optimizar/Validar/Detener.</li>
</ul>
<h3>Atajos</h3>
<ul>
<li><b>Ctrl+O</b> abrir · <b>Ctrl+S</b> guardar</li>
</ul>
<h3>Flujo típico</h3>
<ol>
<li>Importa de Untis o abre un <code>.bjs</code>.</li>
<li>Revisa <b>Datos</b> y <b>Restricciones</b>.</li>
<li><b>Optimiza</b> y ajusta a mano en <b>Horario</b>.</li>
<li>Guarda una <b>versión</b> y exporta los <b>informes</b>.</li>
</ol>
"""


def _docs_index() -> Path:
    return Path(__file__).resolve().parents[3] / "site" / "index.html"


class HelpCenterModule(QWidget):
    """Ayuda integrada y acceso a la documentación del SDK."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge

        browser = QTextBrowser()
        browser.setHtml(_HELP_HTML)

        self._open_docs = QPushButton("Abrir documentación completa del SDK")
        self._open_docs.clicked.connect(self._open)
        index = _docs_index()
        self._open_docs.setEnabled(index.exists())
        if not index.exists():
            self._open_docs.setText("Documentación del SDK no construida (mkdocs build)")

        layout = QVBoxLayout(self)
        layout.addWidget(browser, stretch=1)
        layout.addWidget(self._open_docs)

    def refresh(self) -> None:
        return None

    def _open(self) -> None:
        index = _docs_index()
        if index.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(index)))
