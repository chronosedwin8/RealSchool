"""Pruebas del álgebra simbólica del DSL (Fase 3)."""

from __future__ import annotations

import pytest

from scheduling_platform.dsl import BoolDomain, DslRelOp, IntDomain, Var
from scheduling_platform.dsl.exceptions import DslError


def _int_var(key: str) -> Var:
    return Var(key, IntDomain(0, 10))


def test_construccion_lineal_combina_terminos() -> None:
    x = _int_var("x")
    expr = 2 * x + 3 - x  # -> x + 3
    assert expr.coeffs == ((x, 1),)
    assert expr.constant == 3


def test_terminos_con_coeficiente_cero_se_eliminan() -> None:
    x = _int_var("x")
    expr = x - x + 5
    assert expr.coeffs == ()
    assert expr.constant == 5


def test_coeffs_ordenados_por_key_para_determinismo() -> None:
    a = _int_var("a")
    b = _int_var("b")
    expr = 3 * b + 2 * a
    assert [var.key for var, _ in expr.coeffs] == ["a", "b"]


def test_resta_y_negacion() -> None:
    x = _int_var("x")
    y = _int_var("y")
    expr = -(x - y)  # -x + y
    assert {v.key: c for v, c in expr.coeffs} == {"x": -1, "y": 1}


def test_relacion_normaliza_a_expr_op_cero() -> None:
    x = _int_var("x")
    y = _int_var("y")
    relation = (2 * x) <= (y + 4)  # 2x - y - 4 <= 0
    assert relation.op is DslRelOp.LE
    assert {v.key: c for v, c in relation.expr.coeffs} == {"x": 2, "y": -1}
    assert relation.expr.constant == -4


def test_eq_construye_relacion_de_igualdad() -> None:
    x = _int_var("x")
    relation = x.eq(5)
    assert relation.op is DslRelOp.EQ
    assert relation.expr.coeffs == ((x, 1),)
    assert relation.expr.constant == -5


def test_var_key_vacia_lanza() -> None:
    with pytest.raises(ValueError):
        Var("  ", BoolDomain())


def test_int_domain_invalido_lanza() -> None:
    with pytest.raises(DslError):
        IntDomain(5, 1)


def test_variables_de_expresion() -> None:
    x = _int_var("x")
    y = _int_var("y")
    assert (x + 2 * y).variables() == frozenset({x, y})


def test_operadores_reflejados() -> None:
    x = _int_var("x")
    # 3 + x, 10 - x, 4 * x usan __radd__/__rsub__/__rmul__ de Var
    assert (3 + x).constant == 3
    reflejada = 10 - x  # -x + 10
    assert {v.key: c for v, c in reflejada.coeffs} == {"x": -1}
    assert reflejada.constant == 10
    assert (4 * x).coeffs == ((x, 4),)


def test_relacion_ge_y_expr_rsub() -> None:
    x = _int_var("x")
    y = _int_var("y")
    relation = (x + 1) >= (y - 2)  # x - y + 3 >= 0
    assert relation.op is DslRelOp.GE
    assert {v.key: c for v, c in relation.expr.coeffs} == {"x": 1, "y": -1}
    assert relation.expr.constant == 3
    # __rsub__ de LinearExpr: 5 - (x + 1)
    resta = 5 - (x + 1)
    assert {v.key: c for v, c in resta.coeffs} == {"x": -1}
    assert resta.constant == 4
