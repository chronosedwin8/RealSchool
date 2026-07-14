"""Interfaz del SDK de plugins.

Un plugin lee el :class:`SchedulingModelContext` y devuelve una
:class:`Contribution` con restricciones DSL y (opcionalmente) términos de
penalización para el objetivo. Regla fundamental (Prompt3 §5): un plugin
**nunca** ejecuta código sobre variables del solver ni conoce a OR-Tools; solo
produce definiciones simbólicas que entran en el pipeline de compilación.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from ..dsl.expressions import LinearExpr
from ..dsl.logic import DslConstraint
from .context import SchedulingModelContext


@dataclass(frozen=True, slots=True)
class Contribution:
    """Lo que un plugin aporta al modelo: restricciones y penalizaciones."""

    constraints: tuple[DslConstraint, ...] = ()
    objective_terms: tuple[LinearExpr, ...] = ()


class SchedulingPlugin(ABC):
    """Base de todos los plugins de reglas."""

    name: ClassVar[str]

    @abstractmethod
    def contribute(self, context: SchedulingModelContext) -> Contribution:
        """Produce la contribución del plugin a partir del contexto del modelo."""
