"""Pruebas del adaptador Académico <-> Canónico (Fase 2, prueba estrella)."""

from __future__ import annotations

from hypothesis import given

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
from scheduling_platform.academic.tags import GENERIC_ROOM, group_tag, teacher_tag
from scheduling_platform.core import Assignment, ResourceId, Solution

from .academic_strategies import academic_problems


def _mini_academic() -> AcademicProblem:
    """Mini-colegio: 2 docentes, 2 aulas, 2 grupos, con disponibilidad y un lab."""
    return AcademicProblem(
        time_frame=TimeFrame(day_names=("Lun", "Mar"), periods_per_day=4),
        rooms=(
            Room(RoomId(0), "Aula 101"),
            Room(RoomId(1), "Lab Física", room_type="lab"),
        ),
        teachers=(
            Teacher(TeacherId(0), "Juan"),
            # Ana solo está disponible el lunes (día 0):
            Teacher(TeacherId(1), "Ana", available_periods=frozenset({(0, p) for p in range(4)})),
        ),
        groups=(StudentGroup(GroupId(0), "7A"), StudentGroup(GroupId(1), "7B")),
        subjects=(Subject(SubjectId(0), "Mate"), Subject(SubjectId(1), "Física")),
        assignments=(
            # Juan: Mate a 7A, un bloque doble
            TeachingAssignment(AssignmentId(0), TeacherId(0), SubjectId(0), GroupId(0), (2,)),
            # Ana: Física a 7B en laboratorio, dos sesiones sencillas
            TeachingAssignment(
                AssignmentId(1),
                TeacherId(1),
                SubjectId(1),
                GroupId(1),
                (1, 1),
                required_room_type="lab",
            ),
        ),
    )


def test_traduccion_cuenta_recursos_y_tareas() -> None:
    academic = _mini_academic()
    translation = AcademicToCanonicalAdapter().translate(academic)
    problem = translation.problem
    # recursos = docentes + grupos + aulas
    assert len(problem.resources) == 2 + 2 + 2
    # tareas = suma de sesiones de todas las cargas (2 + (1,1) -> 1 + 2 = 3)
    assert len(problem.tasks) == 3
    assert problem.horizon == 8


def test_grupo_es_recurso_unario() -> None:
    academic = _mini_academic()
    translation = AcademicToCanonicalAdapter().translate(academic)
    # el recurso con el tag de grupo debe ser unario (capacidad 1)
    grupo0 = next(r for r in translation.problem.resources if group_tag(GroupId(0)) in r.tags)
    assert grupo0.capacity == 1


def test_tarea_fija_docente_y_grupo_y_deja_aula_generica() -> None:
    academic = _mini_academic()
    translation = AcademicToCanonicalAdapter().translate(academic)
    # tarea de la carga de Juan (Mate a 7A)
    tarea = translation.problem.tasks[0]
    tags_requeridos = {req.tag for req in tarea.requirements}
    assert teacher_tag(TeacherId(0)) in tags_requeridos
    assert group_tag(GroupId(0)) in tags_requeridos
    assert GENERIC_ROOM in tags_requeridos


def test_disponibilidad_docente_restringe_allowed_starts() -> None:
    academic = _mini_academic()
    translation = AcademicToCanonicalAdapter().translate(academic)
    # Las tareas de Ana (carga 1) solo pueden empezar el lunes (slots 0..3)
    ana_tasks = [
        tid
        for tid, origin in translation.session_origin.items()
        if origin.assignment_id == AssignmentId(1)
    ]
    for tid in ana_tasks:
        task = next(t for t in translation.problem.tasks if t.id == tid)
        assert task.allowed_starts is not None
        assert all(start < 4 for start in task.allowed_starts)


def test_roundtrip_reconstruye_horario_academico() -> None:
    academic = _mini_academic()
    adapter = AcademicToCanonicalAdapter()
    translation = adapter.translate(academic)
    problem = translation.problem

    # Construimos una solución-fixture: cada tarea a su docente/grupo fijos,
    # primer aula compatible, e inicio válido más temprano. (No es un horario
    # optimizado ni libre de conflictos; solo valida el mapeo de vuelta.)
    def resource_with_tag(tag: str) -> ResourceId:
        return next(r.id for r in problem.resources if tag in r.tags)

    assignments = []
    for task in problem.tasks:
        teacher_res = resource_with_tag(task.requirements[0].tag)
        group_res = resource_with_tag(task.requirements[1].tag)
        room_res = resource_with_tag(task.requirements[2].tag)
        start = min(problem.valid_starts_for(task))
        assignments.append(Assignment(task.id, start, (teacher_res, group_res, room_res)))
    solution = Solution(assignments=tuple(assignments), objective_value=0)
    solution.validate_against(problem)  # la fixture es estructuralmente válida

    schedule = translation.to_schedule(solution)
    assert len(schedule.classes) == len(problem.tasks)

    # La clase de Juan (Mate a 7A) debe reconstruirse con sus IDs académicos.
    mate = next(c for c in schedule.classes if c.assignment_id == AssignmentId(0))
    assert mate.teacher_id == TeacherId(0)
    assert mate.subject_id == SubjectId(0)
    assert mate.group_id == GroupId(0)
    assert mate.duration == 2
    # y en un aula real de la institución
    assert mate.room_id in {r.id for r in academic.rooms}
    # Física de Ana debe caer en el laboratorio (único room_type="lab")
    fisica = next(c for c in schedule.classes if c.assignment_id == AssignmentId(1))
    assert fisica.room_id == RoomId(1)


@given(academic_problems())
def test_property_traduccion_produce_problema_canonico_valido(academic: AcademicProblem) -> None:
    translation = AcademicToCanonicalAdapter().translate(academic)
    problem = translation.problem
    esperado_recursos = len(academic.teachers) + len(academic.groups) + len(academic.rooms)
    esperado_tareas = sum(len(a.session_lengths) for a in academic.assignments)
    assert len(problem.resources) == esperado_recursos
    assert len(problem.tasks) == esperado_tareas
    # todos los orígenes están mapeados (biyección de vuelta bien formada)
    assert len(translation.resource_origin) == esperado_recursos
    assert len(translation.session_origin) == esperado_tareas
