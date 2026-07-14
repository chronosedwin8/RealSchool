"""Scoring Engine: función objetivo unificada a partir de penalizaciones.

Las restricciones blandas no se imponen: se traducen a expresiones de holgura
que se penalizan numéricamente y se suman en una única función objetivo
(Prompt3 §2.4). El escalado de pesos evita que un criterio con peso desmesurado
domine a los demás (Prompt3 §3, "normalización").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..dsl.expressions import LinearExpr
from ..dsl.model import Objective
from .base import PenaltyTerm


def normalize_weights(raw: Mapping[str, int], scale: int = 100) -> dict[str, int]:
    """Escala pesos crudos a enteros que suman aproximadamente ``scale``.

    Preserva las proporciones entre criterios y garantiza un peso mínimo de 1,
    de modo que ningún criterio quede anulado ni domine por magnitud arbitraria.
    """
    if scale < 1:
        raise ValueError(f"scale debe ser >= 1: {scale}")
    total = sum(raw.values())
    if total <= 0:
        return dict.fromkeys(raw, 1)
    return {key: max(1, round(value * scale / total)) for key, value in raw.items()}


@dataclass(frozen=True, slots=True)
class ScoringEngine:
    """Combina las penalizaciones de los plugins en la función objetivo."""

    def build_objective(self, penalties: Sequence[PenaltyTerm]) -> Objective | None:
        """Objetivo unificado ``minimizar sum(peso_i * holgura_i)``.

        Devuelve ``None`` si no hay penalizaciones (problema de pura
        factibilidad, sin criterio de calidad que optimizar).
        """
        if not penalties:
            return None
        expr = LinearExpr.of(0)
        for penalty in penalties:
            expr = expr + penalty.weight * penalty.expr
        return Objective(expr)

    def weights_by_label(self, penalties: Sequence[PenaltyTerm]) -> dict[str, int]:
        """Peso acumulado por criterio (base del Informe de Penalizaciones)."""
        weights: dict[str, int] = {}
        for penalty in penalties:
            weights[penalty.label] = weights.get(penalty.label, 0) + penalty.weight
        return weights
