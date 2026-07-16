"""Configuración industrial: engine.yaml / plugins.yaml sin Pydantic (H3)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from scheduling_platform.application import (
    ConfigError,
    ConfigValidateCommand,
    EngineConfig,
    PluginsConfig,
    PluginSetting,
    load_engine_config,
    load_plugins_config,
    solver_factory_for,
)
from scheduling_platform.application.dispatcher import CommandDispatcher
from scheduling_platform.sal.ortools_solver import ORToolsSolver

_ENGINE_YAML = """
engine:
  version: "1.0.0"
  default_solver: highs
  threads: 4
  max_time_seconds: 120
  random_seed: 7
"""

_PLUGINS_YAML = """
plugins:
  - id: teacher_gaps
    enabled: true
    tier: 1
    weight: 150
    params:
      min_gap_duration_minutes: 30
  - id: teacher_room_stability
    enabled: true
    tier: 2
    weight: 100
  - id: daily_span
    enabled: false
"""


# --- EngineConfig ---


def test_engine_config_valido() -> None:
    cfg = load_engine_config(_ENGINE_YAML)
    assert cfg.default_solver == "highs"
    assert cfg.threads == 4
    sc = cfg.to_solver_config()
    assert sc.num_search_workers == 4
    assert sc.max_time_in_seconds == 120
    assert sc.random_seed == 7


def test_engine_solver_desconocido_falla() -> None:
    with pytest.raises(ConfigError, match="default_solver"):
        load_engine_config("engine:\n  default_solver: gurobi_pro\n")


def test_engine_threads_invalido_falla() -> None:
    with pytest.raises(ConfigError, match="threads"):
        EngineConfig(threads=0).validate()


def test_engine_tipo_invalido_falla() -> None:
    with pytest.raises(ConfigError, match="threads"):
        load_engine_config("engine:\n  threads: ocho\n")


def test_solver_factory_resolucion() -> None:
    assert solver_factory_for("ortools_cpsat") is ORToolsSolver
    assert solver_factory_for("cbc")().backend == "CBC"  # type: ignore[attr-defined]
    with pytest.raises(ConfigError, match="desconocido"):
        solver_factory_for("no_existe")


# --- PluginsConfig ---


def test_plugins_config_valido_y_construye_registro() -> None:
    cfg = load_plugins_config(_PLUGINS_YAML)
    assert len(cfg.plugins) == 3
    registry = cfg.build_registry()
    names = registry.names()
    assert "teacher_gaps" in names
    assert "teacher_room_stability" in names
    assert "daily_span" not in names  # deshabilitado
    # los tiers configurados quedan operativos en el scoring
    assert registry.scoring.tier_by_label["teacher_gaps"] == 1
    assert registry.scoring.tier_by_label["teacher_room_stability"] == 2


def test_plugin_desconocido_falla() -> None:
    with pytest.raises(ConfigError, match="desconocido"):
        PluginsConfig((PluginSetting(id="no_existe"),)).validate()


def test_plugin_tier_fuera_de_rango_falla() -> None:
    with pytest.raises(ConfigError, match="tier"):
        PluginsConfig((PluginSetting(id="teacher_gaps", tier=9),)).validate()


def test_plugin_peso_no_positivo_falla() -> None:
    with pytest.raises(ConfigError, match="peso"):
        PluginsConfig((PluginSetting(id="teacher_gaps", weight=0),)).validate()


def test_plugin_duplicado_falla() -> None:
    with pytest.raises(ConfigError, match="duplicado"):
        PluginsConfig(
            (PluginSetting(id="teacher_gaps"), PluginSetting(id="teacher_gaps"))
        ).validate()


def test_plugins_lista_mal_formada_falla() -> None:
    with pytest.raises(ConfigError, match="lista"):
        load_plugins_config("plugins:\n  id: suelto\n")


# --- Comando config validate ---


def test_config_validate_command_ok(tmp_path: Path) -> None:
    engine_file = tmp_path / "engine.yaml"
    plugins_file = tmp_path / "plugins.yaml"
    engine_file.write_text(_ENGINE_YAML, encoding="utf-8")
    plugins_file.write_text(_PLUGINS_YAML, encoding="utf-8")

    out, err = io.StringIO(), io.StringIO()
    code = CommandDispatcher().dispatch(
        ConfigValidateCommand(str(engine_file), str(plugins_file)), out=out, err=err
    )
    assert code == 0
    assert '"valid": true' in out.getvalue()
    assert "plugins.yaml OK" in err.getvalue()


def test_config_validate_command_error_es_exit_1(tmp_path: Path) -> None:
    bad = tmp_path / "engine.yaml"
    bad.write_text("engine:\n  default_solver: inventado\n", encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = CommandDispatcher().dispatch(ConfigValidateCommand(str(bad)), out=out, err=err)
    assert code == 1
    assert out.getvalue() == ""
    assert "default_solver" in err.getvalue()
