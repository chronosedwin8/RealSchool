"""Pruebas del SDK de plugins (Fase 6)."""

from __future__ import annotations

import pytest

from scheduling_platform.academic import (
    AcademicProblem,
    AcademicToCanonicalAdapter,
    AssignmentId,
    GroupId,
    Room,
    RoomId,
    StudentGroup,
    Subject,
    SubjectId,
    Teacher,
    TeacherId,
    TeachingAssignment,
    TimeFrame,
)
from scheduling_platform.core import (
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Task,
    TaskId,
    TimeGrid,
)
from scheduling_platform.plugins import (
    Contribution,
    PluginRegistry,
    SchedulingModelContext,
    SchedulingPlugin,
    catalog,
    discover_plugins,
    registry_with,
)
from scheduling_platform.plugins.catalog.common import ForbiddenStartsPlugin
from scheduling_platform.plugins.catalog.teacher import TeacherLunchPlugin
from scheduling_platform.sal import FakeSolver, SolverStatus

from .plugin_contract import assert_plugin_contract


def _canonical_problem() -> SchedulingProblem:
    # 1 docente (teacher#0), 2 aulas, 2 clases de 1 período en horizonte 4.
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([4]),
        resources=(
            Resource(ResourceId(0), "Prof. Juan", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula 1", frozenset({"room"})),
            Resource(ResourceId(2), "Aula 2", frozenset({"room"})),
        ),
        tasks=(
            Task(
                TaskId(0),
                "Mate",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            ),
            Task(
                TaskId(1),
                "Física",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            ),
        ),
    )


def _context() -> SchedulingModelContext:
    return SchedulingModelContext.build(_canonical_problem())


# --- Contexto y restricciones estructurales ---


def test_contexto_declara_variables_esperadas() -> None:
    context = _context()
    keys = context.all_variable_keys()
    assert context.start_var(0, 0).key in keys
    assert context.assign_var(0, 1).key in keys  # tarea 0 puede usar Aula 1


def test_restricciones_estructurales_una_por_inicio_y_requerimiento() -> None:
    context = _context()
    structural = context.structural_constraints()
    # 2 tareas: cada una 1 (exactly-one-start) + 2 requerimientos = 3 -> 6
    assert len(structural) == 6


# --- Contrato de plugin ---


def test_teacher_lunch_cumple_contrato() -> None:
    assert_plugin_contract(TeacherLunchPlugin(lunch_slots=frozenset({2})), _context())


def test_forbidden_starts_cumple_contrato() -> None:
    assert_plugin_contract(ForbiddenStartsPlugin(forbidden=frozenset({(0, 1)})), _context())


# --- Registro, activación y ensamblado ---


def test_activar_desactivar_cambia_el_modelo() -> None:
    context = _context()
    registry = PluginRegistry()
    registry.register(TeacherLunchPlugin(lunch_slots=frozenset({2})))
    con_plugin = registry.build_model(context)

    registry.disable("teacher_lunch")
    sin_plugin = registry.build_model(context)

    # el plugin agrega restricciones (prohibe iniciar en el slot de almuerzo)
    assert len(con_plugin.constraints) > len(sin_plugin.constraints)
    # sin plugins, solo quedan las estructurales
    assert len(sin_plugin.constraints) == len(context.structural_constraints())


def test_registro_rechaza_duplicados() -> None:
    registry = PluginRegistry()
    registry.register(TeacherLunchPlugin())
    with pytest.raises(ValueError):
        registry.register(TeacherLunchPlugin())


def test_habilitar_plugin_desconocido_lanza() -> None:
    with pytest.raises(KeyError):
        PluginRegistry().enable("inexistente")


def test_registro_expone_nombres_y_estado() -> None:
    registry = PluginRegistry()
    registry.register(TeacherLunchPlugin(), enabled=False)
    registry.register(ForbiddenStartsPlugin())
    assert registry.names() == ("forbidden_starts", "teacher_lunch")
    assert registry.is_enabled("forbidden_starts") is True
    assert registry.is_enabled("teacher_lunch") is False
    registry.enable("teacher_lunch")
    assert registry.is_enabled("teacher_lunch") is True


def test_deshabilitar_plugin_desconocido_lanza() -> None:
    with pytest.raises(KeyError):
        PluginRegistry().disable("inexistente")


# --- Descubrimiento automático ---


def test_discovery_encuentra_los_plugins_del_catalogo() -> None:
    clases = discover_plugins(catalog)
    nombres = {cls.name for cls in clases}
    assert "teacher_lunch" in nombres
    assert "forbidden_starts" in nombres


# --- Plugin de tercero, sin modificar el núcleo ---


class _ThirdPartyPlugin(SchedulingPlugin):
    name = "tercero_bloquea_slot_0"

    def contribute(self, context: SchedulingModelContext) -> Contribution:
        from scheduling_platform.dsl.logic import LinearConstraint

        constraints = tuple(
            LinearConstraint(context.start_var(int(task.id), 0).eq(0))
            for task in context.problem.tasks
            if 0 in context.valid_starts(int(task.id))
        )
        return Contribution(constraints=constraints)


def test_plugin_de_tercero_se_integra_sin_tocar_el_nucleo() -> None:
    context = _context()
    registry = registry_with([_ThirdPartyPlugin()])
    model = registry.build_model(context)
    base = len(context.structural_constraints())
    assert len(model.constraints) == base + 2  # una por tarea que puede iniciar en 0


# --- End-to-end a través del pipeline con FakeSolver ---


def test_teacher_lunch_end_to_end_con_pipeline() -> None:
    from scheduling_platform.pipeline import OptimizationPipeline

    problem = _canonical_problem()
    context = SchedulingModelContext.build(problem)
    registry = registry_with([TeacherLunchPlugin(lunch_slots=frozenset({3}))])
    model = registry.build_model(context)

    solver = FakeSolver()
    solver.set_result(SolverStatus.OPTIMAL, {}, objective_value=0)
    result = OptimizationPipeline().run(problem, model, solver)

    assert result.status is SolverStatus.OPTIMAL
    # el núcleo/pipeline nunca menciona "teacher_lunch": el plugin es opaco
    assert result.var_map is not None


def test_pipeline_con_plugins_sobre_problema_academico() -> None:
    from scheduling_platform.pipeline import OptimizationPipeline

    academic = AcademicProblem(
        time_frame=TimeFrame(("Lun",), 4),
        rooms=(Room(RoomId(0), "A1"), Room(RoomId(1), "A2")),
        teachers=(Teacher(TeacherId(0), "Juan"),),
        groups=(StudentGroup(GroupId(0), "7A"),),
        subjects=(Subject(SubjectId(0), "Mate"),),
        assignments=(
            TeachingAssignment(AssignmentId(0), TeacherId(0), SubjectId(0), GroupId(0), (1,)),
        ),
    )
    translation = AcademicToCanonicalAdapter().translate(academic)
    context = SchedulingModelContext.build(translation.problem)
    registry = registry_with([TeacherLunchPlugin(lunch_slots=frozenset({3}))])
    model = registry.build_model(context)

    solver = FakeSolver()
    solver.set_result(SolverStatus.FEASIBLE, {})
    result = OptimizationPipeline().run(translation.problem, model, solver)
    assert result.status is SolverStatus.FEASIBLE
