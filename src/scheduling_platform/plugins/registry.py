"""Registro y descubrimiento de plugins.

El núcleo jamás se modifica para agregar una regla: los plugins se registran
(explícitamente o por descubrimiento) y se activan/desactivan dinámicamente. El
registro ensambla el ``DslModel`` combinando las restricciones estructurales del
contexto con las contribuciones de los plugins activos.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Iterable
from functools import reduce
from operator import add
from types import ModuleType

from ..dsl.expressions import LinearExpr
from ..dsl.logic import DslConstraint
from ..dsl.model import DslModel, Objective
from .base import SchedulingPlugin
from .context import SchedulingModelContext


class PluginRegistry:
    """Contiene los plugins registrados y cuáles están activos."""

    def __init__(self) -> None:
        self._plugins: dict[str, SchedulingPlugin] = {}
        self._enabled: set[str] = set()

    def register(self, plugin: SchedulingPlugin, *, enabled: bool = True) -> None:
        if plugin.name in self._plugins:
            raise ValueError(f"plugin ya registrado: {plugin.name}")
        self._plugins[plugin.name] = plugin
        if enabled:
            self._enabled.add(plugin.name)

    def enable(self, name: str) -> None:
        self._require_known(name)
        self._enabled.add(name)

    def disable(self, name: str) -> None:
        self._require_known(name)
        self._enabled.discard(name)

    def is_enabled(self, name: str) -> bool:
        return name in self._enabled

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def enabled_plugins(self) -> tuple[SchedulingPlugin, ...]:
        return tuple(self._plugins[name] for name in sorted(self._enabled))

    def build_model(self, context: SchedulingModelContext) -> DslModel:
        constraints: list[DslConstraint] = list(context.structural_constraints())
        objective_terms: list[LinearExpr] = []
        for plugin in self.enabled_plugins():
            contribution = plugin.contribute(context)
            constraints.extend(contribution.constraints)
            objective_terms.extend(contribution.objective_terms)
        objective = Objective(reduce(add, objective_terms)) if objective_terms else None
        return DslModel(tuple(constraints), objective)

    def _require_known(self, name: str) -> None:
        if name not in self._plugins:
            raise KeyError(f"plugin no registrado: {name}")


def discover_plugins(package: ModuleType) -> tuple[type[SchedulingPlugin], ...]:
    """Descubre las clases de plugin definidas en los módulos de ``package``."""
    found: list[type[SchedulingPlugin]] = []
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, SchedulingPlugin)
                and obj is not SchedulingPlugin
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return tuple(sorted(found, key=lambda cls: cls.name))


def registry_with(plugins: Iterable[SchedulingPlugin]) -> PluginRegistry:
    """Atajo: crea un registro con los plugins dados, todos activos."""
    registry = PluginRegistry()
    for plugin in plugins:
        registry.register(plugin)
    return registry
