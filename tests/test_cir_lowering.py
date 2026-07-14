"""Pruebas de lowering DSL->CIR, serialización y compilador CIR->ISolver (Fase 4)."""

from __future__ import annotations

from scheduling_platform.cir import (
    CirAllDifferent,
    CirBoolOr,
    CirImplication,
    CirLinear,
    CirLiteral,
    CirModel,
    CirObjective,
    CirToSolverCompiler,
    cir_to_text,
    lower,
)
from scheduling_platform.dsl import (
    AllDifferentConstraint,
    BoolDomain,
    BoolOrConstraint,
    DslLiteral,
    DslModel,
    ImplicationConstraint,
    IntDomain,
    LinearConstraint,
    Objective,
    Var,
)
from scheduling_platform.sal import FakeSolver, RelOp


def test_lowering_convierte_menor_estricto() -> None:
    x = Var("x", IntDomain(0, 5))
    model = DslModel(constraints=(LinearConstraint(x < 3),))
    cir = lower(model)
    assert cir.constraints == (CirLinear((("x", 1),), RelOp.LE, 2),)


def test_lowering_convierte_mayor_estricto() -> None:
    x = Var("x", IntDomain(0, 5))
    cir = lower(DslModel(constraints=(LinearConstraint(x > 3),)))
    assert cir.constraints == (CirLinear((("x", 1),), RelOp.GE, 4),)


def test_lowering_objetivo() -> None:
    x = Var("x", IntDomain(0, 5))
    y = Var("y", IntDomain(0, 5))
    cir = lower(
        DslModel(constraints=(LinearConstraint(x + y >= 1),), objective=Objective(3 * x + 2 * y))
    )
    assert cir.objective == CirObjective((("x", 3), ("y", 2)), 0)


def test_serializacion_snapshot() -> None:
    x = Var("x", IntDomain(0, 5))
    y = Var("y", BoolDomain())
    model = DslModel(
        constraints=(
            LinearConstraint((2 * x + 1) <= 6),
            BoolOrConstraint((DslLiteral(y),)),
        ),
        objective=Objective(3 * x),
    )
    text = cir_to_text(lower(model))
    assert text == (
        "VARS\n"
        "  x: int[0,5]\n"
        "  y: bool\n"
        "CONSTRAINTS\n"
        "  LINEAR 2*x <= 5\n"
        "  BOOLOR y\n"
        "OBJECTIVE\n"
        "  minimize 3*x + 0"
    )


def test_lowering_y_serializacion_de_todos_los_nodos() -> None:
    a = Var("a", IntDomain(0, 3))
    b = Var("b", IntDomain(0, 3))
    p = Var("p", BoolDomain())
    q = Var("q", BoolDomain())
    model = DslModel(
        constraints=(
            AllDifferentConstraint((a, b)),
            ImplicationConstraint(DslLiteral(p), DslLiteral(q, positive=False)),
        )
    )
    cir = lower(model)
    assert cir.constraints == (
        CirAllDifferent(("a", "b")),
        CirImplication(CirLiteral("p"), CirLiteral("q", positive=False)),
    )
    text = cir_to_text(cir)
    assert "ALLDIFF a, b" in text
    assert "IMPL p -> ~q" in text


def test_compilador_cir_baja_alldiff_e_implicacion() -> None:
    model = CirModel(
        variables=(
            ("a", IntDomain(0, 3)),
            ("b", IntDomain(0, 3)),
            ("p", BoolDomain()),
            ("q", BoolDomain()),
        ),
        constraints=(
            CirAllDifferent(("a", "b")),
            CirImplication(CirLiteral("p"), CirLiteral("q")),
        ),
    )
    solver = FakeSolver()
    CirToSolverCompiler().compile(model, solver)
    assert len(solver.all_different) == 1
    assert len(solver.implications) == 1


def test_compilador_cir_a_fake_solver() -> None:
    model = CirModel(
        variables=(("x", IntDomain(0, 5)), ("y", BoolDomain())),
        constraints=(
            CirLinear((("x", 2), ("y", 1)), RelOp.LE, 8),
            CirBoolOr((CirLiteral("y"),)),
        ),
        objective=CirObjective((("x", 1),), 0),
    )
    solver = FakeSolver()
    var_map = CirToSolverCompiler().compile(model, solver)
    assert set(var_map) == {"x", "y"}
    assert len(solver.linear_constraints) == 1
    assert solver.linear_constraints[0].op is RelOp.LE
    assert solver.linear_constraints[0].rhs == 8
    assert len(solver.bool_ors) == 1
    assert solver.has_objective
