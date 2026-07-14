"""Referencia por fuerza bruta para las pruebas de preservación semántica.

Enumera TODAS las asignaciones posibles sobre los dominios (pequeños) de las
variables de un CIR y devuelve el conjunto exacto de soluciones factibles.
Comparar este conjunto antes y después de un pase demuestra que el pase
preserva la semántica. Solo para pruebas: es exponencial y se usa con modelos
diminutos.
"""

from __future__ import annotations

from itertools import product

from scheduling_platform.cir import CirModel, satisfies
from scheduling_platform.dsl.domain import BoolDomain, IntDomain

Assignment = frozenset[tuple[str, int]]


def _domain_values(model: CirModel, key: str) -> range:
    domain = model.domain_of(key)
    if isinstance(domain, BoolDomain):
        return range(0, 2)
    if isinstance(domain, IntDomain):
        return range(domain.lo, domain.hi + 1)
    raise TypeError(f"dominio no enumerable: {domain!r}")


def solution_set(model: CirModel) -> set[Assignment]:
    """Conjunto de todas las asignaciones factibles del modelo (fuerza bruta)."""
    keys = model.variable_keys()
    domains = [list(_domain_values(model, key)) for key in keys]
    solutions: set[Assignment] = set()
    for combo in product(*domains):
        assignment = dict(zip(keys, combo, strict=True))
        if satisfies(model, assignment):
            solutions.add(frozenset(assignment.items()))
    return solutions
