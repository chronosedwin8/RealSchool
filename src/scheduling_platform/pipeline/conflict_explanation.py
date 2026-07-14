"""Conflict Explanation Engine.

Único lugar que convierte una infactibilidad en una explicación legible: agrupa
los hallazgos del Graph Builder y las razones de una
:class:`StructuralContradictionError` del CIR en un :class:`ConflictReport`.
Garantiza que el motor nunca devuelva un "INFEASIBLE" mudo.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..cir.exceptions import StructuralContradictionError
from .issues import ConflictReport, StructuralIssue


class ConflictExplanationEngine:
    """Traduce hallazgos estructurales a un informe accionable."""

    def explain_structural(self, issues: Sequence[StructuralIssue]) -> ConflictReport:
        return ConflictReport(feasible=not issues, issues=tuple(issues))

    def explain_contradiction(self, error: StructuralContradictionError) -> ConflictReport:
        issues = tuple(
            StructuralIssue(kind="cir_contradiction", message=reason) for reason in error.reasons
        )
        return ConflictReport(feasible=False, issues=issues)
