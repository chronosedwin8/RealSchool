"""Pruebas de los Optimizer Passes (Fase 4): preservación semántica y contradicciones.

Estas son las pruebas de rigor más importantes del proyecto: para modelos CIR
diminutos se enumera el espacio completo de soluciones y se verifica que cada
pase (y el pipeline completo) lo preserva; y que las contradicciones sembradas
se detectan antes del solver, coincidiendo con un espacio de soluciones vacío.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scheduling_platform.cir import (
    CirLinear,
    CirModel,
    DeduplicateConstraints,
    DetectContradictions,
    FuseComparableLinear,
    PassManager,
    RemoveTrivialConstraints,
    ReorderForPropagation,
    SimplifyLinearByGcd,
    StructuralContradictionError,
)
from scheduling_platform.cir.passes import CirPass
from scheduling_platform.dsl.domain import BoolDomain, IntDomain
from scheduling_platform.sal import RelOp

from .cir_reference import solution_set
from .cir_strategies import cir_models

_INT = IntDomain(0, 3)
_BOOL = BoolDomain()
_VARS = (("a", _INT), ("b", _INT), ("p", _BOOL), ("q", _BOOL))

_PRESERVING_PASSES: list[CirPass] = [
    SimplifyLinearByGcd(),
    DeduplicateConstraints(),
    FuseComparableLinear(),
    RemoveTrivialConstraints(),
    ReorderForPropagation(),
]


@given(cir_models(), st.integers(min_value=0, max_value=len(_PRESERVING_PASSES) - 1))
def test_cada_pase_preserva_la_semantica(model: CirModel, pass_index: int) -> None:
    cir_pass = _PRESERVING_PASSES[pass_index]
    result = cir_pass.run(model)
    assert solution_set(result) == solution_set(model)


@given(cir_models())
def test_pipeline_completo_preserva_o_detecta_infactibilidad(model: CirModel) -> None:
    base = solution_set(model)
    try:
        result = PassManager.default().run(model)
    except StructuralContradictionError:
        # Si el pipeline declara contradicción, el espacio de soluciones debe ser vacío.
        assert base == set()
    else:
        assert solution_set(result) == base


@given(cir_models())
def test_differential_pases_on_vs_off(model: CirModel) -> None:
    # Pipeline sin ningún pase = identidad; comparamos factibilidad con el default.
    identidad = PassManager(())
    con_pases = PassManager.default()
    base = solution_set(identidad.run(model))
    try:
        optimizado = solution_set(con_pases.run(model))
    except StructuralContradictionError:
        assert base == set()
    else:
        assert optimizado == base


# --- Deduplicación y fusión (casos dirigidos) ---


def test_deduplica_restricciones_identicas() -> None:
    c = CirLinear((("a", 1),), RelOp.LE, 2)
    model = CirModel(_VARS, (c, c, c))
    result = DeduplicateConstraints().run(model)
    assert result.constraints == (c,)


def test_fusiona_conserva_cota_mas_estricta() -> None:
    model = CirModel(
        _VARS,
        (CirLinear((("a", 1),), RelOp.LE, 3), CirLinear((("a", 1),), RelOp.LE, 1)),
    )
    result = FuseComparableLinear().run(model)
    assert result.constraints == (CirLinear((("a", 1),), RelOp.LE, 1),)


def test_simplifica_por_gcd() -> None:
    model = CirModel(_VARS, (CirLinear((("a", 2), ("b", 4)), RelOp.LE, 7),))
    result = SimplifyLinearByGcd().run(model)
    # 2a + 4b <= 7  ->  a + 2b <= 3
    assert result.constraints == (CirLinear((("a", 1), ("b", 2)), RelOp.LE, 3),)


def test_elimina_trivial_siempre_verdadera() -> None:
    model = CirModel(_VARS, (CirLinear((), RelOp.LE, 5), CirLinear((("a", 1),), RelOp.LE, 2)))
    result = RemoveTrivialConstraints().run(model)
    assert result.constraints == (CirLinear((("a", 1),), RelOp.LE, 2),)


# --- Detección de contradicciones (sembradas) ---


def test_detecta_constante_imposible() -> None:
    model = CirModel(_VARS, (CirLinear((), RelOp.EQ, 1),))  # 0 == 1
    with pytest.raises(StructuralContradictionError):
        DetectContradictions().run(model)


def test_detecta_igualdad_sin_solucion_entera() -> None:
    model = CirModel(_VARS, (CirLinear((("a", 2),), RelOp.EQ, 3),))  # 2a == 3
    with pytest.raises(StructuralContradictionError):
        DetectContradictions().run(model)


def test_detecta_valor_fuera_de_dominio() -> None:
    model = CirModel(_VARS, (CirLinear((("a", 1),), RelOp.EQ, 9),))  # a == 9, dom [0,3]
    with pytest.raises(StructuralContradictionError):
        DetectContradictions().run(model)


def test_detecta_igualdades_en_conflicto() -> None:
    model = CirModel(
        _VARS,
        (CirLinear((("a", 1),), RelOp.EQ, 1), CirLinear((("a", 1),), RelOp.EQ, 2)),
    )
    with pytest.raises(StructuralContradictionError) as exc:
        DetectContradictions().run(model)
    assert exc.value.reasons  # lleva razones legibles


def test_modelo_consistente_no_lanza() -> None:
    model = CirModel(_VARS, (CirLinear((("a", 1),), RelOp.EQ, 2),))
    assert DetectContradictions().run(model) is model


def test_passmanager_without_excluye_pases() -> None:
    pm = PassManager.default().without("reorder", "detect_contradictions")
    names = {p.name for p in pm.passes}
    assert "reorder" not in names
    assert "detect_contradictions" not in names
