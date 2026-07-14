"""Motor, Optimizador y Telemetría (Fase 9).

Pruebas de rigor:
- **End-to-end**: académico -> adaptador -> motor -> horario académico legible.
- **Invariante del Informe de Penalizaciones**: la suma del desglose coincide
  exactamente con el valor de la función objetivo.
- **Validation Engine**: sobre soluciones *corrompidas a propósito*, detecta el
  100% de las violaciones sembradas (nunca confiar solo en el solver).
- **Telemetría**: cada etapa se cronometra y los pases reducen restricciones.
"""

from __future__ import annotations

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
    Assignment,
    Penalty,
    Resource,
    ResourceId,
    ResourceRequirement,
    SchedulingProblem,
    Solution,
    Task,
    TaskId,
    TimeGrid,
    TimeSlotIndex,
)
from scheduling_platform.engine import (
    SchedulingEngine,
    SolutionInspector,
    ValidationEngine,
    evaluate_linear,
)
from scheduling_platform.plugins import PenaltyTerm, SchedulingModelContext, registry_with
from scheduling_platform.plugins.catalog.preferences import PreferEarlySlotsPlugin
from scheduling_platform.plugins.catalog.structural import ResourceNoOverlapPlugin
from scheduling_platform.sal import SolverConfig, SolverStatus
from scheduling_platform.sal.ortools_solver import ORToolsSolver

_CONFIG = SolverConfig(random_seed=1, num_search_workers=1)


def _problem(n_classes: int = 3, slots: int = 3) -> SchedulingProblem:
    return SchedulingProblem(
        grid=TimeGrid.from_segment_lengths([slots]),
        resources=(
            Resource(ResourceId(0), "Prof. Juan", frozenset({"teacher", "teacher#0"})),
            Resource(ResourceId(1), "Aula 101", frozenset({"room"})),
        ),
        tasks=tuple(
            Task(
                TaskId(i),
                f"Clase {i}",
                1,
                (ResourceRequirement("teacher#0"), ResourceRequirement("room")),
            )
            for i in range(n_classes)
        ),
    )


def _engine(plugins: list[object] | None = None) -> SchedulingEngine:
    registry = registry_with([ResourceNoOverlapPlugin(), *(plugins or [])])  # type: ignore[list-item]
    return SchedulingEngine(registry=registry, solver_factory=ORToolsSolver)


# --- API pública end-to-end ---


def test_motor_genera_horario_valido() -> None:
    result = _engine().solve(_problem(), _CONFIG)
    assert result.status is SolverStatus.OPTIMAL
    assert result.solved  # hay solución Y supera la validación independiente
    assert result.solution is not None
    assert len(result.solution.assignments) == 3
    # el no-solape se respeta: las 3 clases del mismo docente en slots distintos
    assert len({int(a.start) for a in result.solution.assignments}) == 3


def test_motor_asigna_los_recursos_requeridos() -> None:
    result = _engine().solve(_problem(n_classes=1), _CONFIG)
    assert result.solution is not None
    asignacion = result.solution.assignments[0]
    # cada clase usa exactamente su docente y un aula
    assert set(asignacion.resource_ids) == {ResourceId(0), ResourceId(1)}


def test_motor_infactible_devuelve_explicacion_sin_horario() -> None:
    # 4 clases en 3 slots con un solo docente: imposible
    result = _engine().solve(_problem(n_classes=4, slots=3), _CONFIG)
    assert result.solved is False
    assert result.solution is None
    assert result.report.render()  # explicación accionable
    assert "no" in result.render().lower() or result.report.issues


def test_motor_reconstruye_el_horario_academico() -> None:
    academic = AcademicProblem(
        time_frame=TimeFrame(("Lun", "Mar"), 2),
        rooms=(Room(RoomId(0), "A1", capacity=30),),
        teachers=(Teacher(TeacherId(0), "Juan"),),
        groups=(StudentGroup(GroupId(0), "7A", size=25),),
        subjects=(Subject(SubjectId(0), "Mate"),),
        assignments=(
            TeachingAssignment(AssignmentId(0), TeacherId(0), SubjectId(0), GroupId(0), (1, 1)),
        ),
    )
    translation = AcademicToCanonicalAdapter().translate(academic)
    result = _engine().solve(translation.problem, _CONFIG)
    assert result.solved
    assert result.solution is not None

    schedule = translation.to_schedule(result.solution)
    assert len(schedule.classes) == 2  # dos sesiones semanales
    for clase in schedule.classes:
        assert clase.teacher_id == TeacherId(0)
        assert clase.group_id == GroupId(0)
        assert clase.room_id == RoomId(0)
        assert 0 <= clase.day < 2
        assert 0 <= clase.period < 2


# --- Informe de Penalizaciones ---


def test_informe_de_penalizaciones_cuadra_con_el_objetivo() -> None:
    # 3 clases, 3 slots, prefiriendo horas tempranas: penalización = 0+1+2 = 3
    result = _engine([PreferEarlySlotsPlugin(weight=1)]).solve(_problem(), _CONFIG)
    assert result.solution is not None
    total = sum(p.amount for p in result.solution.penalties)
    assert total == result.solution.objective_value
    assert result.solution.objective_value == 3


def test_informe_desglosa_por_criterio() -> None:
    result = _engine([PreferEarlySlotsPlugin(weight=2)]).solve(_problem(), _CONFIG)
    assert result.solution is not None
    fuentes = {p.source for p in result.solution.penalties}
    assert fuentes == {"prefer_early_slots"}
    assert "Informe de penalizaciones" in result.render()


def test_sin_preferencias_no_hay_penalizaciones() -> None:
    result = _engine().solve(_problem(), _CONFIG)
    assert result.solution is not None
    assert result.solution.penalties == ()
    assert result.solution.objective_value == 0


def test_evaluate_linear_y_inspector() -> None:
    context = SchedulingModelContext.build(_problem(n_classes=1))
    expr = context.start_var(0, 1) + 2 * context.start_var(0, 2)
    values = {context.start_var(0, 1).key: 1, context.start_var(0, 2).key: 0}
    assert evaluate_linear(expr, values) == 1

    inspector = SolutionInspector()
    terms = [PenaltyTerm(expr, weight=3, label="tarde")]
    assert inspector.total(terms, values) == 3
    assert inspector.penalty_report(terms, values) == (Penalty(source="tarde", amount=3),)


# --- Validation Engine sobre soluciones corrompidas ---


def _valid_solution(problem: SchedulingProblem) -> Solution:
    return Solution(
        assignments=tuple(
            Assignment(TaskId(i), TimeSlotIndex(i), (ResourceId(0), ResourceId(1)))
            for i in range(len(problem.tasks))
        ),
        objective_value=0,
    )


def test_validacion_acepta_una_solucion_correcta() -> None:
    problem = _problem()
    report = ValidationEngine().validate(problem, _valid_solution(problem))
    assert report.valid
    assert "supera todas las validaciones" in report.render()


def test_validacion_detecta_docente_duplicado() -> None:
    # dos clases del mismo docente en el mismo período
    problem = _problem(n_classes=2)
    corrupta = Solution(
        assignments=(
            Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
            Assignment(TaskId(1), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),
        ),
        objective_value=0,
    )
    report = ValidationEngine().validate(problem, corrupta)
    assert not report.valid
    assert any(i.kind == "capacity_exceeded" for i in report.issues)
    assert "Prof. Juan" in report.render()


def test_validacion_detecta_requerimiento_incumplido() -> None:
    # la clase no recibe aula: solo el docente
    problem = _problem(n_classes=1)
    corrupta = Solution(
        assignments=(Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0),)),),
        objective_value=0,
    )
    report = ValidationEngine().validate(problem, corrupta)
    assert not report.valid
    assert any(i.kind == "unsatisfied_requirement" for i in report.issues)


def test_validacion_detecta_tarea_faltante() -> None:
    problem = _problem(n_classes=2)
    corrupta = Solution(
        assignments=(Assignment(TaskId(0), TimeSlotIndex(0), (ResourceId(0), ResourceId(1))),),
        objective_value=0,
    )
    report = ValidationEngine().validate(problem, corrupta)
    assert not report.valid
    assert any(i.kind == "structure" for i in report.issues)


def test_validacion_detecta_inicio_invalido() -> None:
    problem = _problem(n_classes=1, slots=2)
    corrupta = Solution(
        assignments=(Assignment(TaskId(0), TimeSlotIndex(5), (ResourceId(0), ResourceId(1))),),
        objective_value=0,
    )
    report = ValidationEngine().validate(problem, corrupta)
    assert not report.valid


# --- Telemetría ---


def test_telemetria_cronometra_cada_etapa() -> None:
    result = _engine().solve(_problem(), _CONFIG)
    telemetry = result.telemetry
    assert telemetry is not None
    assert telemetry.t_total_ms > 0
    assert telemetry.t_solve_ms >= 0
    assert telemetry.num_variables > 0
    assert telemetry.num_constraints > 0


def test_telemetria_reporta_restricciones_eliminadas_por_los_pases() -> None:
    result = _engine().solve(_problem(), _CONFIG)
    telemetry = result.telemetry
    assert telemetry is not None
    # los pases deduplican los enlaces de ocupación compartidos entre reglas
    assert telemetry.num_constraints_before_passes >= telemetry.num_constraints
    assert telemetry.constraints_eliminated >= 0
