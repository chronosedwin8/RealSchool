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
from types import ModuleType

from ..dsl.logic import DslConstraint
from ..dsl.model import DslModel
from .base import PenaltyTerm, SchedulingPlugin
from .context import SchedulingModelContext
from .scoring import ScoringEngine


class PluginRegistry:
    """Contiene los plugins registrados y cuáles están activos."""

    def __init__(self, scoring: ScoringEngine | None = None) -> None:
        self._plugins: dict[str, SchedulingPlugin] = {}
        self._enabled: set[str] = set()
        self._scoring = scoring if scoring is not None else ScoringEngine()

    @property
    def scoring(self) -> ScoringEngine:
        """El Scoring Engine con el que se construye la función objetivo."""
        return self._scoring

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

    def build(self, context: SchedulingModelContext) -> tuple[DslModel, tuple[PenaltyTerm, ...]]:
        """Ensambla el modelo y sus penalizaciones en **una sola pasada**.

        Consultar a los plugins es caro en instituciones grandes, así que se les
        pregunta una única vez (antes se les llamaba dos: una para el modelo y
        otra para las penalizaciones).
        """
        constraints: list[DslConstraint] = list(context.structural_constraints())
        penalties: list[PenaltyTerm] = []
        for plugin in self.enabled_plugins():
            contribution = plugin.contribute(context)
            constraints.extend(contribution.constraints)
            penalties.extend(contribution.penalties)
        objective = self._scoring.build_objective(penalties)
        return DslModel(tuple(constraints), objective), tuple(penalties)

    def build_model(self, context: SchedulingModelContext) -> DslModel:
        """Solo el modelo (atajo sobre :meth:`build`)."""
        return self.build(context)[0]

    def collect_penalties(self, context: SchedulingModelContext) -> tuple[PenaltyTerm, ...]:
        """Solo las penalizaciones (atajo sobre :meth:`build`)."""
        return self.build(context)[1]

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
