"""Hallazgos de infactibilidad estructural y su informe legible.

Un :class:`StructuralIssue` describe una razón concreta por la que el problema
no tiene solución, con un mensaje accionable. El :class:`ConflictReport` los
agrupa; su ``render`` produce el texto que verá el usuario (nunca un
"INFEASIBLE" mudo).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StructuralIssue:
    """Una causa concreta de infactibilidad detectada antes del solver."""

    kind: str
    message: str
    entities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConflictReport:
    """Resultado del análisis de factibilidad pre-solver."""

    feasible: bool
    issues: tuple[StructuralIssue, ...] = ()

    def render(self) -> str:
        if self.feasible:
            return "Sin conflictos estructurales detectados."
        lines = ["Conflictos estructurales detectados:"]
        lines.extend(f"- [{issue.kind}] {issue.message}" for issue in self.issues)
        return "\n".join(lines)
