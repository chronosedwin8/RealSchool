"""Desglose del objetivo CP-SAT por criterio de la ponderación (ADR-036).

Cada término que emiten los plugins del puente lleva como etiqueta un criterio
de `Weighting` (o un término interno, como el cambio mínimo). Este módulo lleva
el objetivo de una `Solution` a ese vocabulario, para la pestaña Análisis.
"""

from __future__ import annotations

from typing import Final

from scheduling_platform.core import Solution
from scheduling_platform.engine import MetricsEngine
from scheduling_platform.untis_model import Weighting

#: Etiquetas internas que no son deslizadores (se muestran aparte).
INTERNAL_LABELS: Final[frozenset[str]] = frozenset({"minimal_change", "minimal_change_room"})


def criterion_points(solution: Solution) -> dict[str, int]:
    """`criterio -> puntos` del objetivo CP-SAT, solo criterios de la ponderación."""
    desglose = MetricsEngine().breakdown(solution)
    validos = set(Weighting.criteria())
    return {c.criterion: c.points for c in desglose.by_criterion if c.criterion in validos}


def unknown_labels(labels: set[str]) -> set[str]:
    """Etiquetas que no son ni criterio de la ponderación ni término interno."""
    return labels - set(Weighting.criteria()) - INTERNAL_LABELS


__all__ = ["INTERNAL_LABELS", "criterion_points", "unknown_labels"]
