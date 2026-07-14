"""Plugin SDK (Fase 6).

Las reglas de negocio (duras y blandas) se implementan como plugins que
declaran restricciones vía DSL. El núcleo jamás se modifica para agregar una
regla nueva: se registran y activan/desactivan dinámicamente a través del
:class:`PluginRegistry`. No se importa ``ortools`` aquí.
"""

from __future__ import annotations

from .base import Contribution, SchedulingPlugin
from .context import SchedulingModelContext
from .registry import PluginRegistry, discover_plugins, registry_with

__all__ = [
    "Contribution",
    "PluginRegistry",
    "SchedulingModelContext",
    "SchedulingPlugin",
    "discover_plugins",
    "registry_with",
]
