"""Pruebas del compilador DSL -> ISolver contra FakeSolver (Fase 3)."""

from __future__ import annotations

import pytest

from scheduling_platform.dsl import (
    AllDifferentConstraint,
    BoolDomain,
    BoolOrConstraint,
    DslLiteral,
    DslModel,
    DslToSolverCompiler,
    ImplicationConstraint,
    IntDomain,
    LinearConstraint,
    Objective,
    Var,
)
from scheduling_platform.dsl.exceptions import DslError
from scheduling_platform.sal import FakeSolver, RelOp


def test_variable_lineal_llega_al_solver() -> None:
    x = Var("x", IntDomain(0, 5))
    y = Var("y", IntDomain(0, 5))
    model = DslModel(constraints=(LinearConstraint((2 * x + y) <= 8),))
    solver = FakeSolver()

    var_map = DslToSolverCompiler().compile(model, solver)

    # dos variables enteras creadas
    assert len(var_map) == 2
    assert set(solver.var_kind.values()) == {"int"}
    # una restricción lineal: 2x + y <= 8
    assert len(solver.linear_constraints) == 1
    record = solver.linear_constraints[0]
    assert record.op is RelOp.LE
    assert record.rhs == 8
    coefs = {solver.var_name[v]: c for v, c in record.terms}
    assert coefs == {"x": 2, "y": 1}


def test_menor_estricto_ajusta_rhs() -> None:
    x = Var("x", IntDomain(0, 5))
    model = DslModel(constraints=(LinearConstraint(x < 3),))  # x <= 2
    solver = FakeSolver()
    DslToSolverCompiler().compile(model, solver)
    record = solver.linear_constraints[0]
    assert record.op is RelOp.LE
    assert record.rhs == 2


def test_mayor_estricto_ajusta_rhs() -> None:
    x = Var("x", IntDomain(0, 5))
    model = DslModel(constraints=(LinearConstraint(x > 3),))  # x >= 4
    solver = FakeSolver()
    DslToSolverCompiler().compile(model, solver)
    record = solver.linear_constraints[0]
    assert record.op is RelOp.GE
    assert record.rhs == 4


def test_all_different_se_baja() -> None:
    variables = tuple(Var(f"v{i}", IntDomain(0, 3)) for i in range(3))
    model = DslModel(constraints=(AllDifferentConstraint(variables),))
    solver = FakeSolver()
    DslToSolverCompiler().compile(model, solver)
    assert len(solver.all_different) == 1
    assert len(solver.all_different[0]) == 3


def test_bool_or_con_negacion_se_baja() -> None:
    a = Var("a", BoolDomain())
    b = Var("b", BoolDomain())
    model = DslModel(constraints=(BoolOrConstraint((DslLiteral(a), ~DslLiteral(b))),))
    solver = FakeSolver()
    DslToSolverCompiler().compile(model, solver)
    assert len(solver.bool_ors) == 1
    literals = solver.bool_ors[0]
    positives = {solver.var_name[lit.var]: lit.positive for lit in literals}
    assert positives == {"a": True, "b": False}


def test_implicacion_se_baja() -> None:
    a = Var("a", BoolDomain())
    b = Var("b", BoolDomain())
    model = DslModel(constraints=(ImplicationConstraint(DslLiteral(a), DslLiteral(b)),))
    solver = FakeSolver()
    DslToSolverCompiler().compile(model, solver)
    assert len(solver.implications) == 1
    imp = solver.implications[0]
    assert solver.var_name[imp.antecedent.var] == "a"
    assert solver.var_name[imp.consequent.var] == "b"


def test_objetivo_se_minimiza() -> None:
    x = Var("x", IntDomain(0, 5))
    y = Var("y", IntDomain(0, 5))
    model = DslModel(
        constraints=(LinearConstraint(x + y >= 1),),
        objective=Objective(3 * x + 2 * y),
    )
    solver = FakeSolver()
    DslToSolverCompiler().compile(model, solver)
    assert solver.has_objective
    coefs = {solver.var_name[v]: c for v, c in solver.objective_terms}
    assert coefs == {"x": 3, "y": 2}


def test_key_repetida_con_dominios_distintos_lanza() -> None:
    # dos Var con la misma key pero dominios distintos: error de modelado
    x_int = Var("dup", IntDomain(0, 5))
    x_bool = Var("dup", BoolDomain())
    model = DslModel(
        constraints=(LinearConstraint(x_int >= 1), BoolOrConstraint((DslLiteral(x_bool),)))
    )
    solver = FakeSolver()
    with pytest.raises(DslError):
        DslToSolverCompiler().compile(model, solver)


def test_literal_requiere_variable_booleana() -> None:
    x = Var("x", IntDomain(0, 5))
    with pytest.raises(DslError):
        DslLiteral(x)


def test_all_different_requiere_dos_variables() -> None:
    with pytest.raises(DslError):
        AllDifferentConstraint((Var("v0", IntDomain(0, 3)),))


def test_bool_or_requiere_al_menos_un_literal() -> None:
    with pytest.raises(DslError):
        BoolOrConstraint(())


def test_igualdad_se_baja_como_eq() -> None:
    x = Var("x", IntDomain(0, 5))
    model = DslModel(constraints=(LinearConstraint(x.eq(3)),))
    solver = FakeSolver()
    DslToSolverCompiler().compile(model, solver)
    record = solver.linear_constraints[0]
    assert record.op is RelOp.EQ
    assert record.rhs == 3
