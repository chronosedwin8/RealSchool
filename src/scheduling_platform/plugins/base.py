"""Interfaz del SDK de plugins.

Un plugin lee el :class:`SchedulingModelContext` y devuelve una
:class:`Contribution` con:

- **restricciones duras** (Rule Engine): DSL que el solver debe satisfacer;
- **penalizaciones** (Scoring Engine): términos de holgura ponderados que se
  minimizan en la función objetivo unificada.

Regla fundamental (Prompt3 §5): un plugin **nunca** ejecuta código sobre
variables del solver ni conoce a OR-Tools; solo produce definiciones simbólicas
que entran en el pipeline de compilación.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from ..dsl.expressions import LinearExpr
from ..dsl.logic import DslConstraint
from .context import SchedulingModelContext


@dataclass(frozen=True, slots=True)
class PenaltyTerm:
    """Penalización de una restricción blanda.

    ``expr`` es una expresión lineal no negativa (holgura: cuántas veces y con
    qué intensidad se incumple la preferencia). ``weight`` es su importancia
    relativa y ``label`` identifica el criterio en el Informe de Penalizaciones.

    ``tier`` es el nivel lexicográfico (1 vital, 2 operativa, 3 preferencial); el
    Scoring Engine aplica un multiplicador de escala por Tier para que una
    violación de prioridad alta pese más que cualquier cantidad de las bajas.
    ``theoretical_max`` es el peor caso posible de la holgura: si se indica, el
    Scoring Engine normaliza la penalización dividiéndola por él (rango comparable
    entre criterios de escalas distintas). Los valores por defecto (Tier 3, sin
    máximo) reproducen el comportamiento histórico ``coef = weight``.
    """

    expr: LinearExpr
    weight: int
    label: str
    tier: int = 3
    theoretical_max: int | None = None

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError(f"el peso de una penalización debe ser > 0: {self.weight}")
        if not self.label.strip():
            raise ValueError("la penalización necesita una etiqueta")
        if self.tier not in (1, 2, 3):
            raise ValueError(f"tier debe ser 1, 2 o 3: {self.tier}")
        if self.theoretical_max is not None and self.theoretical_max <= 0:
            raise ValueError(f"theoretical_max debe ser > 0 o None: {self.theoretical_max}")


@dataclass(frozen=True, slots=True)
class Contribution:
    """Lo que un plugin aporta al modelo: restricciones duras y penalizaciones."""

    constraints: tuple[DslConstraint, ...] = ()
    penalties: tuple[PenaltyTerm, ...] = ()


class SchedulingPlugin(ABC):
    """Base de todos los plugins de reglas."""

    name: ClassVar[str]

    @abstractmethod
    def contribute(self, context: SchedulingModelContext) -> Contribution:
        """Produce la contribución del plugin a partir del contexto del modelo."""
