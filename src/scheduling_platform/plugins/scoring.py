"""Scoring Engine: función objetivo unificada, jerarquizada por Tiers.

Las restricciones blandas no se imponen: se traducen a expresiones de holgura que
se penalizan numéricamente y se suman en una única función objetivo (Prompt3
§2.4). Para que un criterio no domine a otro por su escala, el motor aplica
(Prompt3 §3.C, ADR-020):

1. **Normalización por máximo teórico**: cada holgura se divide por su peor caso
   ``theoretical_max`` para llevar todas las violaciones a un rango comparable.
2. **Jerarquía por Tiers**: un multiplicador de escala por nivel lexicográfico
   (Tier 1 vital 10000, Tier 2 operativa 100, Tier 3 preferencial 1) garantiza
   que una violación de prioridad alta pese más que cualquier cantidad de
   violaciones de prioridad baja.

Como CP-SAT solo admite coeficientes enteros, la normalización se pliega en un
único coeficiente entero por término:
``coef = round(E_tier · W · SCALE / s_max)`` (mínimo 1). Con Tier 3 y sin máximo
teórico, ``coef = W`` — comportamiento idéntico al histórico (retrocompatibilidad).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..dsl.expressions import LinearExpr
from ..dsl.model import Objective
from .base import PenaltyTerm

#: Multiplicador de escala por Tier (nivel lexicográfico).
TIER_SCALE: dict[int, int] = {1: 10_000, 2: 100, 3: 1}

#: Tier por defecto de un término sin clasificar (preferencial).
DEFAULT_TIER = 3


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
    """Combina las penalizaciones de los plugins en la función objetivo.

    ``tier_by_label`` permite asignar el Tier de un criterio por su etiqueta
    (lo usa ``registry_from_catalog`` para volver operativos los Tiers del
    catálogo). Vacío, cada término conserva su propio ``tier`` (por defecto 3).
    """

    tier_by_label: Mapping[str, int] = field(default_factory=dict)
    scale: int = 1000

    def tier_of(self, term: PenaltyTerm) -> int:
        return self.tier_by_label.get(term.label, term.tier)

    def effective_coefficient(self, term: PenaltyTerm) -> int:
        """Coeficiente entero del término: escala de Tier por peso por normalización."""
        escala = TIER_SCALE.get(self.tier_of(term), 1)
        if term.theoretical_max and term.theoretical_max > 0:
            return max(1, round(escala * term.weight * self.scale / term.theoretical_max))
        return escala * term.weight

    def build_objective(self, penalties: Sequence[PenaltyTerm]) -> Objective | None:
        """Objetivo unificado ``minimizar sum(coef_i * holgura_i)``.

        Devuelve ``None`` si no hay penalizaciones (problema de pura
        factibilidad, sin criterio de calidad que optimizar).
        """
        if not penalties:
            return None
        expr = LinearExpr.of(0)
        for penalty in penalties:
            expr = expr + self.effective_coefficient(penalty) * penalty.expr
        return Objective(expr)

    def weights_by_label(self, penalties: Sequence[PenaltyTerm]) -> dict[str, int]:
        """Peso acumulado por criterio (base del Informe de Penalizaciones)."""
        weights: dict[str, int] = {}
        for penalty in penalties:
            weights[penalty.label] = weights.get(penalty.label, 0) + penalty.weight
        return weights
