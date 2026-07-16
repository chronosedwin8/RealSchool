"""Catálogo canónico de restricciones (Actividad 2)."""

from __future__ import annotations

from scheduling_platform.plugins import (
    CONSTRAINT_CATALOG,
    ConstraintKind,
    plugin_names_in_catalog,
    registry_from_catalog,
    render_catalog_table,
)
from scheduling_platform.plugins import catalog as catalog_pkg
from scheduling_platform.plugins.catalog.daily_quality import TeacherGapsPlugin
from scheduling_platform.plugins.registry import discover_plugins


def test_ids_unicos_y_no_vacios() -> None:
    ids = [d.id for d in CONSTRAINT_CATALOG]
    assert len(ids) == len(set(ids))
    for d in CONSTRAINT_CATALOG:
        assert d.id and d.name and d.description


def test_toda_soft_tiene_tier_y_peso() -> None:
    for d in CONSTRAINT_CATALOG:
        if d.kind is ConstraintKind.SOFT:
            assert d.tier in (1, 2, 3), d.id
            assert d.default_weight is not None and d.default_weight > 0, d.id
        else:
            assert d.tier is None, d.id


def test_las_hard_no_llevan_peso_finito() -> None:
    for d in CONSTRAINT_CATALOG:
        if d.kind is ConstraintKind.HARD:
            assert d.weight_label == "∞"


def test_cobertura_bidireccional_catalogo_plugins() -> None:
    # Todo plugin del repo tiene una entrada en el catálogo y viceversa.
    repo_plugins = {cls.name for cls in discover_plugins(catalog_pkg)}
    catalog_plugins = plugin_names_in_catalog()
    assert catalog_plugins <= repo_plugins, catalog_plugins - repo_plugins
    assert repo_plugins <= catalog_plugins, repo_plugins - catalog_plugins


def test_registry_from_catalog_instancia_los_que_tienen_factory() -> None:
    ids = [d.id for d in CONSTRAINT_CATALOG if d.factory is not None]
    registry = registry_from_catalog(ids)
    # HC-01/02/03 comparten plugin: se deduplica por nombre.
    assert "interval_no_overlap" in registry.names()
    assert "teacher_gaps" in registry.names()
    assert len(registry.names()) == len(set(registry.names()))


def test_registry_from_catalog_aplica_override_de_peso() -> None:
    registry = registry_from_catalog(["SC-02"], weight_overrides={"SC-02": 7})
    plugin = registry.enabled_plugins()[0]
    assert isinstance(plugin, TeacherGapsPlugin)
    assert plugin.weight == 7


def test_registry_from_catalog_rechaza_id_desconocida() -> None:
    try:
        registry_from_catalog(["ZZ-99"])
    except KeyError:
        return
    raise AssertionError("debía rechazar una ID fuera del catálogo")


def test_render_catalog_table_lista_todas() -> None:
    table = render_catalog_table()
    for d in CONSTRAINT_CATALOG:
        assert d.id in table
