"""Carga de ``engine.yaml`` / ``plugins.yaml`` a dataclasses, con errores claros.

Usa PyYAML (ya dependencia) y valida tipos y estructura con mensajes accionables
(campo + valor + lo esperado), en vez de trazas crípticas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..errors import ConfigError
from .engine_config import EngineConfig
from .plugins_config import PluginsConfig, PluginSetting, instantiable_plugin_ids


def _parse_yaml(text: str) -> Any:
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML inválido: {exc}") from exc


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field} debe ser un entero: {value!r}")
    return value


def _as_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field} debe ser un número: {value!r}")
    return float(value)


def _opt_int(item: dict[str, Any], key: str) -> int | None:
    return None if item.get(key) is None else _as_int(item[key], key)


def engine_config_from_mapping(section: dict[str, Any]) -> EngineConfig:
    """Construye un :class:`EngineConfig` validado desde un mapa ya parseado."""
    if not isinstance(section, dict):
        raise ConfigError("la sección 'engine' debe ser un mapa")
    config = EngineConfig(
        version=str(section.get("version", "1.0.0")),
        default_solver=str(section.get("default_solver", "ortools_cpsat")),
        threads=_as_int(section.get("threads", 8), "engine.threads"),
        max_time_seconds=_as_float(
            section.get("max_time_seconds", 600.0), "engine.max_time_seconds"
        ),
        random_seed=_as_int(section.get("random_seed", 42), "engine.random_seed"),
    )
    config.validate()
    return config


def plugins_config_from_list(items: list[Any]) -> PluginsConfig:
    """Construye un :class:`PluginsConfig` validado desde una lista ya parseada."""
    if not isinstance(items, list):
        raise ConfigError("'plugins' debe ser una lista")
    valid = instantiable_plugin_ids()
    settings: list[PluginSetting] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ConfigError(f"plugins[{i}] debe ser un mapa")
        if "id" not in item:
            raise ConfigError(f"plugins[{i}] requiere el campo 'id'")
        # Ignora ajustes de plugins que ya no se configuran por catálogo (p. ej.
        # 'subject_spread', ahora controlado por una opción del proyecto): así los
        # proyectos guardados con versiones anteriores siguen abriendo.
        if str(item["id"]) not in valid:
            continue
        params = item.get("params", {})
        if not isinstance(params, dict):
            raise ConfigError(f"plugins[{i}].params debe ser un mapa")
        settings.append(
            PluginSetting(
                id=str(item["id"]),
                enabled=bool(item.get("enabled", True)),
                tier=_opt_int(item, "tier"),
                weight=_opt_int(item, "weight"),
                params=dict(params),
            )
        )
    config = PluginsConfig(tuple(settings))
    config.validate()
    return config


def load_engine_config(text: str) -> EngineConfig:
    """Parsea el texto de ``engine.yaml`` a un :class:`EngineConfig` validado."""
    data = _parse_yaml(text)
    if not isinstance(data, dict):
        raise ConfigError("engine.yaml debe ser un mapa")
    return engine_config_from_mapping(data.get("engine", data))


def load_plugins_config(text: str) -> PluginsConfig:
    """Parsea el texto de ``plugins.yaml`` a un :class:`PluginsConfig` validado."""
    data = _parse_yaml(text)
    items = data.get("plugins", []) if isinstance(data, dict) else data
    return plugins_config_from_list(items)


def load_engine_config_file(path: str | Path) -> EngineConfig:
    target = Path(path)
    if not target.exists():
        raise ConfigError(f"no existe el archivo de configuración: {target}")
    return load_engine_config(target.read_text(encoding="utf-8"))


def load_plugins_config_file(path: str | Path) -> PluginsConfig:
    target = Path(path)
    if not target.exists():
        raise ConfigError(f"no existe el archivo de configuración: {target}")
    return load_plugins_config(target.read_text(encoding="utf-8"))
