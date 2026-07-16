"""Rigor de la Fase 3 (B6): round-trip .bjs property-based sobre problemas arbitrarios.

El determinismo git-friendly, la atomicidad y la resiliencia ante corrupción ya
se prueban en test_bjs_container / test_bjs_validation / test_cli_project. Aquí se
somete el **split/merge** (calendar/resources/tasks) y el ciclo de Git
(extract -> editar -> pack) a instituciones sintéticas generadas por Hypothesis.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings

from scheduling_platform.academic import AcademicProblem, AcademicToCanonicalAdapter
from scheduling_platform.application import BjsProject, open_project, save_project
from scheduling_platform.application.project import pack_project
from scheduling_platform.serialization.bjs import extract
from scheduling_platform.serialization.codec import problem_to_dict

from .academic_strategies import academic_problems


@given(academic_problems())
@settings(max_examples=40, deadline=None)
def test_property_roundtrip_bjs_preserva_el_problema(academic: AcademicProblem) -> None:
    problem = AcademicToCanonicalAdapter().translate(academic).problem
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "p.bjs"
        save_project(path, BjsProject.create("x", problem))
        reloaded = open_project(path)
    assert problem_to_dict(reloaded.problem) == problem_to_dict(problem)


@given(academic_problems())
@settings(max_examples=30, deadline=None)
def test_property_extract_pack_preserva_el_problema(academic: AcademicProblem) -> None:
    # el flujo git: empaquetar -> extraer JSONs -> re-empaquetar -> abrir
    problem = AcademicToCanonicalAdapter().translate(academic).problem
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        original = base / "p.bjs"
        save_project(original, BjsProject.create("x", problem))
        extract(original, base / "src")
        repacked = base / "repack.bjs"
        pack_project(base / "src", repacked)  # re-empaqueta y valida
        reloaded = open_project(repacked)
    assert problem_to_dict(reloaded.problem) == problem_to_dict(problem)
