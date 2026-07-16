"""Plugin SDK, Rule Engine y Scoring Engine (Fases 6 y 8).

Las reglas de negocio se implementan como plugins que declaran restricciones
vía DSL (**duras**, Rule Engine) y penalizaciones ponderadas (**blandas**,
Scoring Engine). El núcleo jamás se modifica para agregar una regla: se
registran y activan/desactivan dinámicamente a través del
:class:`PluginRegistry`, que ensambla la función objetivo unificada. No se
importa ``ortools`` aquí.
"""

from __future__ import annotations

from .base import Contribution, PenaltyTerm, SchedulingPlugin
from .constraint_catalog import (
    CONSTRAINT_CATALOG,
    ConstraintDefinition,
    ConstraintKind,
    catalog_by_id,
    plugin_names_in_catalog,
    registry_from_catalog,
    render_catalog_table,
)
from .context import SchedulingModelContext
from .registry import PluginRegistry, discover_plugins, registry_with
from .scoring import ScoringEngine, normalize_weights

__all__ = [
    "CONSTRAINT_CATALOG",
    "ConstraintDefinition",
    "ConstraintKind",
    "Contribution",
    "PenaltyTerm",
    "PluginRegistry",
    "SchedulingModelContext",
    "SchedulingPlugin",
    "ScoringEngine",
    "catalog_by_id",
    "discover_plugins",
    "normalize_weights",
    "plugin_names_in_catalog",
    "registry_from_catalog",
    "registry_with",
    "render_catalog_table",
]
