"""App de escritorio RealSchool (Fase 6): cliente visual del motor headless.

Competidor de Untis construido sobre PySide6. **Solo** consume la Fachada
``EngineService`` y sus modelos de vista (``scheduling_platform.application``):
nunca toca el problema canónico, el solver ni el pipeline. Toda la lógica vive en
el motor; aquí solo hay presentación.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
