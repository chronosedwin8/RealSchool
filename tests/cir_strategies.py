"""Estrategias de Hypothesis para generar modelos CIR diminutos (Fase 4).

Variables fijas y de dominio pequeño (``a``, ``b`` enteras [0,3]; ``p``, ``q``
booleanas) para que la enumeración exhaustiva de ``solution_set`` sea barata
(64 asignaciones) y las pruebas de preservación semántica sean tratables.
"""

from __future__ import annotations

from hypothesis import strategies as st

from scheduling_platform.cir import (
    CirAllDifferent,
    CirBoolOr,
    CirConstraint,
    CirImplication,
    CirLinear,
    CirLiteral,
    CirModel,
)
from scheduling_platform.dsl.domain import BoolDomain, IntDomain
from scheduling_platform.sal import RelOp

_INT_KEYS = ["a", "b"]
_BOOL_KEYS = ["p", "q"]
_ALL_KEYS = [*_INT_KEYS, *_BOOL_KEYS]
_VARIABLES = (
    ("a", IntDomain(0, 3)),
    ("b", IntDomain(0, 3)),
    ("p", BoolDomain()),
    ("q", BoolDomain()),
)


@st.composite
def _linear(draw: st.DrawFn) -> CirLinear:
    keys = draw(st.lists(st.sampled_from(_ALL_KEYS), min_size=1, max_size=2, unique=True))
    coef = st.integers(min_value=-2, max_value=2).filter(lambda c: c != 0)
    terms = tuple((key, draw(coef)) for key in keys)
    op = draw(st.sampled_from([RelOp.LE, RelOp.GE, RelOp.EQ]))
    rhs = draw(st.integers(min_value=-3, max_value=3))
    return CirLinear.make(terms, op, rhs)


@st.composite
def _bool_or(draw: st.DrawFn) -> CirBoolOr:
    keys = draw(st.lists(st.sampled_from(_BOOL_KEYS), min_size=1, max_size=2, unique=True))
    literals = tuple(CirLiteral(key, draw(st.booleans())) for key in keys)
    return CirBoolOr(literals)


@st.composite
def _implication(draw: st.DrawFn) -> CirImplication:
    a_key = draw(st.sampled_from(_BOOL_KEYS))
    b_key = draw(st.sampled_from(_BOOL_KEYS))
    return CirImplication(
        CirLiteral(a_key, draw(st.booleans())), CirLiteral(b_key, draw(st.booleans()))
    )


def _constraint() -> st.SearchStrategy[CirConstraint]:
    return st.one_of(_linear(), _bool_or(), _implication(), st.just(CirAllDifferent(("a", "b"))))


@st.composite
def cir_models(draw: st.DrawFn) -> CirModel:
    n = draw(st.integers(min_value=1, max_value=4))
    constraints = tuple(draw(_constraint()) for _ in range(n))
    return CirModel(_VARIABLES, constraints)
