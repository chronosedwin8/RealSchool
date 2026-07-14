"""Optimizer Passes sobre el CIR (Prompt3 §2.3).

Cada pase transforma un :class:`CirModel` en otro semánticamente equivalente
(mismo espacio de soluciones) más simple o mejor propagable, salvo
:class:`DetectContradictions`, que solo verifica y lanza si el modelo es
estructuralmente infactible. Todos los pases se comprueban con pruebas de
preservación semántica por enumeración exhaustiva (Fase 4).

Pases incluidos:
- :class:`SimplifyLinearByGcd` — divide una restricción lineal por el mcd de
  sus coeficientes (ajustando el rhs por integralidad).
- :class:`DeduplicateConstraints` — elimina restricciones idénticas.
- :class:`FuseComparableLinear` — entre lineales con los mismos términos y
  operador, conserva la cota más estricta; en EQ incompatibles emite una
  restricción falsa canónica.
- :class:`RemoveTrivialConstraints` — elimina restricciones constantes siempre
  verdaderas.
- :class:`DetectContradictions` — detecta infactibilidad estructural.
- :class:`ReorderForPropagation` — reordena para favorecer la propagación.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from math import gcd
from typing import ClassVar

from ..dsl.domain import BoolDomain, Domain, IntDomain
from ..sal.interface import RelOp
from .exceptions import StructuralContradictionError
from .nodes import CirConstraint, CirLinear, CirModel

_FALSE = CirLinear((), RelOp.EQ, 1)  # 0 == 1: restricción canónica siempre falsa


class CirPass(ABC):
    """Transformación de un CIR en otro equivalente."""

    name: ClassVar[str] = "pass"

    @abstractmethod
    def run(self, model: CirModel) -> CirModel: ...


class SimplifyLinearByGcd(CirPass):
    name = "simplify_gcd"

    def run(self, model: CirModel) -> CirModel:
        return model.with_constraints(tuple(self._simplify(c) for c in model.constraints))

    @staticmethod
    def _simplify(constraint: CirConstraint) -> CirConstraint:
        if not isinstance(constraint, CirLinear) or not constraint.terms:
            return constraint
        divisor = 0
        for _, coef in constraint.terms:
            divisor = gcd(divisor, abs(coef))
        if divisor <= 1:
            return constraint
        new_terms = tuple((k, c // divisor) for k, c in constraint.terms)
        match constraint.op:
            case RelOp.LE:  # floor
                return CirLinear(new_terms, RelOp.LE, constraint.rhs // divisor)
            case RelOp.GE:  # ceil
                return CirLinear(new_terms, RelOp.GE, -(-constraint.rhs // divisor))
            case RelOp.EQ:
                if constraint.rhs % divisor != 0:
                    return constraint  # infactible; lo detecta DetectContradictions
                return CirLinear(new_terms, RelOp.EQ, constraint.rhs // divisor)


class DeduplicateConstraints(CirPass):
    name = "deduplicate"

    def run(self, model: CirModel) -> CirModel:
        seen: set[CirConstraint] = set()
        unique: list[CirConstraint] = []
        for constraint in model.constraints:
            if constraint not in seen:
                seen.add(constraint)
                unique.append(constraint)
        return model.with_constraints(tuple(unique))


class FuseComparableLinear(CirPass):
    name = "fuse_linear"

    def run(self, model: CirModel) -> CirModel:
        # clave: (terms, op) -> rhs más estricto
        tightest: dict[tuple[tuple[tuple[str, int], ...], RelOp], int] = {}
        eq_conflict = False
        others: list[CirConstraint] = []
        order: list[tuple[tuple[tuple[str, int], ...], RelOp]] = []
        for constraint in model.constraints:
            if isinstance(constraint, CirLinear) and constraint.terms:
                key = (constraint.terms, constraint.op)
                if key not in tightest:
                    tightest[key] = constraint.rhs
                    order.append(key)
                elif constraint.op is RelOp.LE:
                    tightest[key] = min(tightest[key], constraint.rhs)
                elif constraint.op is RelOp.GE:
                    tightest[key] = max(tightest[key], constraint.rhs)
                elif constraint.rhs != tightest[key]:  # EQ con rhs distinto
                    eq_conflict = True
            else:
                others.append(constraint)

        fused: list[CirConstraint] = [
            CirLinear(terms, op, tightest[(terms, op)]) for terms, op in order
        ]
        fused.extend(others)
        if eq_conflict:
            fused.append(_FALSE)
        return model.with_constraints(tuple(fused))


class RemoveTrivialConstraints(CirPass):
    name = "remove_trivial"

    def run(self, model: CirModel) -> CirModel:
        kept = tuple(c for c in model.constraints if not self._always_true(c))
        return model.with_constraints(kept)

    @staticmethod
    def _always_true(constraint: CirConstraint) -> bool:
        if isinstance(constraint, CirLinear) and not constraint.terms:
            return _const_holds(constraint.op, constraint.rhs)
        return False


class DetectContradictions(CirPass):
    name = "detect_contradictions"

    def run(self, model: CirModel) -> CirModel:
        reasons: list[str] = []
        eq_values: dict[str, int] = {}
        # Índice de dominios O(1). Buscarlos recorriendo la tupla de variables
        # (cientos de miles en instituciones grandes) por cada restricción
        # convertía este pase en cuadrático.
        domains = dict(model.variables)
        for constraint in model.constraints:
            if not isinstance(constraint, CirLinear):
                continue
            if not constraint.terms:
                if not _const_holds(constraint.op, constraint.rhs):
                    reasons.append(
                        f"restricción imposible: 0 {constraint.op.value} {constraint.rhs}"
                    )
                continue
            self._check_linear(constraint, domains, eq_values, reasons)
        if reasons:
            raise StructuralContradictionError(tuple(reasons))
        return model

    def _check_linear(
        self,
        constraint: CirLinear,
        domains: Mapping[str, Domain],
        eq_values: dict[str, int],
        reasons: list[str],
    ) -> None:
        divisor = 0
        for _, coef in constraint.terms:
            divisor = gcd(divisor, abs(coef))
        if constraint.op is RelOp.EQ and constraint.rhs % divisor != 0:
            reasons.append(f"igualdad sin solución entera: {constraint.terms} == {constraint.rhs}")
            return
        # EQ de una sola variable con coeficiente unitario: valor fijado
        if constraint.op is RelOp.EQ and len(constraint.terms) == 1:
            key, coef = constraint.terms[0]
            if constraint.rhs % coef != 0:
                reasons.append(f"igualdad sin solución entera para {key}")
                return
            value = constraint.rhs // coef
            if not _in_domain(domains, key, value):
                reasons.append(f"{key} == {value} está fuera de su dominio")
            elif key in eq_values and eq_values[key] != value:
                reasons.append(f"{key} fijada a valores distintos: {eq_values[key]} y {value}")
            else:
                eq_values[key] = value


class ReorderForPropagation(CirPass):
    name = "reorder"

    def run(self, model: CirModel) -> CirModel:
        ordered = sorted(model.constraints, key=self._priority)
        return model.with_constraints(tuple(ordered))

    @staticmethod
    def _priority(constraint: CirConstraint) -> tuple[int, int]:
        # igualdades primero, luego por número de variables (menos variables antes)
        num_vars = len(constraint.variables())
        family = 2
        if isinstance(constraint, CirLinear):
            family = 0 if constraint.op is RelOp.EQ else 1
        return (family, num_vars)


@dataclass(frozen=True, slots=True)
class PassManager:
    """Aplica una secuencia configurable de pases sobre un CIR."""

    passes: tuple[CirPass, ...]

    @classmethod
    def default(cls) -> PassManager:
        return cls(
            (
                SimplifyLinearByGcd(),
                DeduplicateConstraints(),
                FuseComparableLinear(),
                RemoveTrivialConstraints(),
                DetectContradictions(),
                ReorderForPropagation(),
            )
        )

    def without(self, *names: str) -> PassManager:
        excluded = frozenset(names)
        return PassManager(tuple(p for p in self.passes if p.name not in excluded))

    def run(self, model: CirModel) -> CirModel:
        for cir_pass in self.passes:
            model = cir_pass.run(model)
        return model


def _const_holds(op: RelOp, rhs: int) -> bool:
    """Evalúa ``0 op rhs`` para una restricción lineal sin variables."""
    match op:
        case RelOp.LE:
            return rhs >= 0
        case RelOp.GE:
            return rhs <= 0
        case RelOp.EQ:
            return rhs == 0


def _in_domain(domains: Mapping[str, Domain], key: str, value: int) -> bool:
    domain = domains[key]
    if isinstance(domain, BoolDomain):
        return value in (0, 1)
    if isinstance(domain, IntDomain):
        return domain.lo <= value <= domain.hi
    return True  # pragma: no cover
