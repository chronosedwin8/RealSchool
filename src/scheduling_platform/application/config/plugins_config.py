"""Configuración de restricciones (``plugins.yaml``) sobre el catálogo de Fase 1.

El catálogo canónico (``CONSTRAINT_CATALOG``) **es el esquema**: cada entrada de
``plugins.yaml`` referencia un plugin por su nombre e indica si está activo, su
tier y su peso. La validación comprueba contra el catálogo y la construcción del
``PluginRegistry`` reutiliza ``registry_from_catalog`` — sin Pydantic ni lógica
duplicada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...plugins import (
    CONSTRAINT_CATALOG,
    ConstraintKind,
    PluginRegistry,
    ScoringEngine,
    catalog_by_id,
    registry_from_catalog,
)
from ..errors import ConfigError

# Plugins que razonan período-a-período: exigen la codificación booleana de
# inicios (``boolean_starts=True``). El resto funciona en el modelo compacto.
_PERIOD_PLUGINS: frozenset[str] = frozenset(
    {
        "teacher_gaps",
        "task_continuity",
        "weekly_balance",
        "daily_span",
        "soft_max_consecutive",
        "prefer_early_slots",
        "avoid_slots",
        "max_daily_load",
        "max_consecutive",
        "teacher_lunch",
        "forbidden_starts",
    }
)


def _instantiable() -> dict[str, str]:
    """Nombre de plugin -> ID de restricción, solo los que tienen factory."""
    mapping: dict[str, str] = {}
    for definition in CONSTRAINT_CATALOG:
        if definition.plugin_name and definition.factory is not None:
            mapping.setdefault(definition.plugin_name, definition.id)
    return mapping


@dataclass(frozen=True, slots=True)
class PluginSetting:
    """Activación, tier y peso de una restricción en la configuración."""

    id: str
    enabled: bool = True
    tier: int | None = None
    weight: int | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PluginsConfig:
    """Conjunto de restricciones activas y sus pesos/tiers configurados."""

    plugins: tuple[PluginSetting, ...]

    def requires_boolean_starts(self) -> bool:
        """``True`` si algún plugin activo razona período-a-período."""
        return any(s.enabled and s.id in _PERIOD_PLUGINS for s in self.plugins)

    def validate(self) -> None:
        valid = _instantiable()
        seen: set[str] = set()
        for setting in self.plugins:
            if setting.id in seen:
                raise ConfigError(f"plugin duplicado en plugins.yaml: {setting.id!r}")
            seen.add(setting.id)
            if setting.id not in valid:
                raise ConfigError(
                    f"plugin desconocido o sin factory: {setting.id!r} "
                    f"(válidos: {', '.join(sorted(valid))})"
                )
            if setting.tier is not None and setting.tier not in (1, 2, 3):
                raise ConfigError(f"tier inválido para {setting.id!r}: {setting.tier} (1, 2 o 3)")
            if setting.weight is not None and setting.weight <= 0:
                raise ConfigError(f"peso inválido para {setting.id!r}: {setting.weight} (> 0)")

    def build_registry(self) -> PluginRegistry:
        """Construye el ``PluginRegistry`` con los plugins activos, pesos y tiers."""
        self.validate()
        name_to_cid = _instantiable()
        index = catalog_by_id()
        cids: list[str] = []
        weight_overrides: dict[str, int] = {}
        tier_by_label: dict[str, int] = {}
        for setting in self.plugins:
            if not setting.enabled:
                continue
            cid = name_to_cid[setting.id]
            cids.append(cid)
            if setting.weight is not None:
                weight_overrides[cid] = setting.weight
            definition = index[cid]
            if definition.kind is ConstraintKind.SOFT:
                tier = setting.tier if setting.tier is not None else definition.tier
                if tier is not None:
                    tier_by_label[setting.id] = tier
        scoring = ScoringEngine(tier_by_label=tier_by_label)
        return registry_from_catalog(cids, weight_overrides=weight_overrides, scoring=scoring)
