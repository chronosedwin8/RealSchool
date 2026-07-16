"""Solution Inspector: Informe de Penalizaciones.

Explica *por qué* un horario tiene el score que tiene: evalúa cada término de
holgura sobre la solución y reporta cuánto aportó cada criterio a la función
objetivo. Por construcción, la suma del informe debe coincidir exactamente con
el valor del objetivo (invariante verificado en las pruebas).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..core.solution import Penalty
from ..dsl.expressions import LinearExpr
from ..plugins.base import PenaltyTerm
from ..plugins.scoring import ScoringEngine


def evaluate_linear(expr: LinearExpr, values: Mapping[str, int]) -> int:
    """Evalúa una expresión lineal del DSL sobre una asignación de variables."""
    total = expr.constant
    for var, coef in expr.coeffs:
        total += coef * values.get(var.key, 0)
    return total


class SolutionInspector:
    """Genera el desglose de penalizaciones por criterio.

    Usa el **mismo coeficiente efectivo** que el Scoring Engine construyó en la
    función objetivo (Tiers + normalización), de modo que la suma del informe
    coincide exactamente con el valor del objetivo (invariante). Sin un
    ``ScoringEngine`` explícito, cae al coeficiente crudo ``weight`` (histórico).
    """

    def _coefficient(self, term: PenaltyTerm, scoring: ScoringEngine | None) -> int:
        return scoring.effective_coefficient(term) if scoring is not None else term.weight

    def penalty_report(
        self,
        penalties: Sequence[PenaltyTerm],
        values: Mapping[str, int],
        scoring: ScoringEngine | None = None,
    ) -> tuple[Penalty, ...]:
        """Penalización aportada por cada criterio (agregada por etiqueta)."""
        by_label: dict[str, int] = {}
        for term in penalties:
            amount = self._coefficient(term, scoring) * evaluate_linear(term.expr, values)
            by_label[term.label] = by_label.get(term.label, 0) + amount
        return tuple(
            Penalty(source=label, amount=amount)
            for label, amount in sorted(by_label.items())
            if amount > 0
        )

    def total(
        self,
        penalties: Sequence[PenaltyTerm],
        values: Mapping[str, int],
        scoring: ScoringEngine | None = None,
    ) -> int:
        """Suma ponderada de todas las holguras (debe igualar el objetivo)."""
        return sum(
            self._coefficient(term, scoring) * evaluate_linear(term.expr, values)
            for term in penalties
        )
