"""Álgebra lineal simbólica del DSL: ``Var``, ``LinearExpr`` y ``Relation``.

Los plugins componen expresiones con operadores naturales (``2 * x + 3 * y - 1``)
y relaciones (``expr <= otra``, ``expr.eq(otra)``). Todo es simbólico y
agnóstico del solver; el compilador (``compiler.py``) las baja a llamadas de
``ISolver``.

Nota de diseño: NO se sobrecarga ``==`` porque ``Var``/``LinearExpr`` son
hashables y se usan como claves; la igualdad de modelado se expresa con
``.eq(...)``. Las comparaciones de orden (``<=``, ``>=``, ``<``, ``>``) sí se
sobrecargan porque no afectan al hashing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from .domain import Domain

type ExprLike = "LinearExpr | Var | int"


class DslRelOp(Enum):
    """Operadores relacionales que el DSL sabe expresar."""

    LE = "<="
    GE = ">="
    EQ = "=="
    LT = "<"
    GT = ">"


@dataclass(frozen=True, slots=True)
class Var:
    """Variable simbólica identificada por su ``key`` y su dominio."""

    key: str
    domain: Domain

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("la key de la variable no puede ser vacía")

    # --- construcción de expresiones lineales ---
    def __add__(self, other: ExprLike) -> LinearExpr:
        return LinearExpr.of(self) + other

    def __radd__(self, other: ExprLike) -> LinearExpr:
        return LinearExpr.of(other) + self

    def __sub__(self, other: ExprLike) -> LinearExpr:
        return LinearExpr.of(self) - other

    def __rsub__(self, other: ExprLike) -> LinearExpr:
        return LinearExpr.of(other) - self

    def __mul__(self, factor: int) -> LinearExpr:
        return LinearExpr.of(self) * factor

    def __rmul__(self, factor: int) -> LinearExpr:
        return LinearExpr.of(self) * factor

    def __neg__(self) -> LinearExpr:
        return -LinearExpr.of(self)

    # --- relaciones ---
    def __le__(self, other: ExprLike) -> Relation:
        return LinearExpr.of(self) <= other

    def __ge__(self, other: ExprLike) -> Relation:
        return LinearExpr.of(self) >= other

    def __lt__(self, other: ExprLike) -> Relation:
        return LinearExpr.of(self) < other

    def __gt__(self, other: ExprLike) -> Relation:
        return LinearExpr.of(self) > other

    def eq(self, other: ExprLike) -> Relation:
        return LinearExpr.of(self).eq(other)


@dataclass(frozen=True, slots=True)
class LinearExpr:
    """Forma lineal canónica ``sum(coef_i * var_i) + constant``.

    ``coeffs`` está normalizada: sin variables repetidas, sin coeficientes cero
    y ordenada por ``key`` para determinismo.
    """

    coeffs: tuple[tuple[Var, int], ...]
    constant: int

    @staticmethod
    def _make(pairs: Iterable[tuple[Var, int]], constant: int) -> LinearExpr:
        acc: dict[Var, int] = {}
        for var, coef in pairs:
            acc[var] = acc.get(var, 0) + coef
        items = [(var, coef) for var, coef in acc.items() if coef != 0]
        items.sort(key=lambda pair: pair[0].key)
        return LinearExpr(tuple(items), constant)

    @classmethod
    def of(cls, value: ExprLike) -> LinearExpr:
        if isinstance(value, LinearExpr):
            return value
        if isinstance(value, Var):
            return cls(((value, 1),), 0)
        return cls((), value)

    def __add__(self, other: ExprLike) -> LinearExpr:
        rhs = LinearExpr.of(other)
        return LinearExpr._make([*self.coeffs, *rhs.coeffs], self.constant + rhs.constant)

    def __radd__(self, other: ExprLike) -> LinearExpr:
        return self + other

    def __sub__(self, other: ExprLike) -> LinearExpr:
        return self + (-LinearExpr.of(other))

    def __rsub__(self, other: ExprLike) -> LinearExpr:
        return LinearExpr.of(other) - self

    def __mul__(self, factor: int) -> LinearExpr:
        return LinearExpr._make(
            [(var, coef * factor) for var, coef in self.coeffs], self.constant * factor
        )

    def __rmul__(self, factor: int) -> LinearExpr:
        return self * factor

    def __neg__(self) -> LinearExpr:
        return self * -1

    def __le__(self, other: ExprLike) -> Relation:
        return Relation.build(self, DslRelOp.LE, other)

    def __ge__(self, other: ExprLike) -> Relation:
        return Relation.build(self, DslRelOp.GE, other)

    def __lt__(self, other: ExprLike) -> Relation:
        return Relation.build(self, DslRelOp.LT, other)

    def __gt__(self, other: ExprLike) -> Relation:
        return Relation.build(self, DslRelOp.GT, other)

    def eq(self, other: ExprLike) -> Relation:
        return Relation.build(self, DslRelOp.EQ, other)

    def variables(self) -> frozenset[Var]:
        return frozenset(var for var, _ in self.coeffs)


@dataclass(frozen=True, slots=True)
class Relation:
    """Relación normalizada a la forma ``expr op 0``."""

    expr: LinearExpr
    op: DslRelOp

    @classmethod
    def build(cls, left: ExprLike, op: DslRelOp, right: ExprLike) -> Relation:
        return cls(LinearExpr.of(left) - LinearExpr.of(right), op)

    def variables(self) -> frozenset[Var]:
        return self.expr.variables()
