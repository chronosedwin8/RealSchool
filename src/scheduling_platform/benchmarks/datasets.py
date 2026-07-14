"""Dataset Provider: instancias académicas sintéticas y parametrizables.

Genera instituciones realistas y **factibles por construcción**, de tamaño
controlado, para medir el rendimiento del motor de forma reproducible.

Realismo importante: un aula no es intercambiable con cualquier otra. Cada grupo
tiene un *pool* reducido de aulas (por edificio/planta), lo que mantiene acotado
el número de aulas elegibles por clase. Modelarlo de otro modo (cualquier clase
en cualquiera de las 300 aulas) haría explotar el modelo sin reflejar la
realidad de ningún colegio.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..academic import (
    AcademicProblem,
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


class InfeasibleDataset(ValueError):
    """Los parámetros piden más clases de las que la infraestructura admite."""


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """Parámetros de una institución sintética."""

    name: str
    teachers: int
    rooms: int
    groups: int
    subjects: int
    days: int = 5
    periods_per_day: int = 7
    load_factor: float = 0.6
    """Fracción del horizonte que cada grupo pasa en clase (0-1)."""
    rooms_per_pool: int = 4
    """Aulas elegibles por clase (pool del grupo)."""

    @property
    def horizon(self) -> int:
        return self.days * self.periods_per_day

    @property
    def classes_per_group(self) -> int:
        return max(1, int(self.horizon * self.load_factor))

    @property
    def total_classes(self) -> int:
        return self.groups * self.classes_per_group

    def validate(self) -> None:
        """Comprueba que la instancia puede tener solución."""
        if self.classes_per_group > self.horizon:
            raise InfeasibleDataset(
                f"{self.name}: cada grupo necesita {self.classes_per_group} períodos "
                f"pero la semana solo tiene {self.horizon}."
            )
        oferta_aulas = self.rooms * self.horizon
        if self.total_classes > oferta_aulas:
            raise InfeasibleDataset(
                f"{self.name}: {self.total_classes} clases no caben en "
                f"{oferta_aulas} períodos-aula."
            )
        carga_docente = self.total_classes / self.teachers
        if carga_docente > self.horizon:
            raise InfeasibleDataset(
                f"{self.name}: cada docente tendría {carga_docente:.0f} períodos, "
                f"más que los {self.horizon} de la semana."
            )


def build_academic(spec: DatasetSpec) -> AcademicProblem:
    """Construye la institución sintética descrita por ``spec``."""
    spec.validate()

    pools = max(1, spec.rooms // spec.rooms_per_pool)

    time_frame = TimeFrame(
        day_names=tuple(f"D{d}" for d in range(spec.days)),
        periods_per_day=spec.periods_per_day,
    )
    rooms = tuple(
        Room(
            id=RoomId(i),
            name=f"Aula {i}",
            capacity=30,
            room_type=f"pool{i % pools}",  # el pool restringe las aulas elegibles
        )
        for i in range(spec.rooms)
    )
    teachers = tuple(Teacher(id=TeacherId(i), name=f"Docente {i}") for i in range(spec.teachers))
    groups = tuple(
        StudentGroup(id=GroupId(i), name=f"Grupo {i}", size=25) for i in range(spec.groups)
    )
    subjects = tuple(Subject(id=SubjectId(i), name=f"Materia {i}") for i in range(spec.subjects))

    assignments: list[TeachingAssignment] = []
    next_id = 0
    docente = 0
    for g in range(spec.groups):
        pool = g % pools
        for c in range(spec.classes_per_group):
            assignments.append(
                TeachingAssignment(
                    id=AssignmentId(next_id),
                    teacher_id=TeacherId(docente % spec.teachers),
                    subject_id=SubjectId(c % spec.subjects),
                    group_id=GroupId(g),
                    session_lengths=(1,),
                    required_room_type=f"pool{pool}",
                )
            )
            next_id += 1
            docente += 1  # reparto rotatorio: carga equilibrada entre docentes

    return AcademicProblem(
        time_frame=time_frame,
        rooms=rooms,
        teachers=teachers,
        groups=groups,
        subjects=subjects,
        assignments=tuple(assignments),
    )


# --- Presets (topologías del framework de benchmarking) ---

SMALL = DatasetSpec(name="DS-01 Colegio Pequeño", teachers=20, rooms=15, groups=15, subjects=8)
MEDIUM = DatasetSpec(name="DS-02 Colegio Mediano", teachers=80, rooms=60, groups=60, subjects=12)
LARGE = DatasetSpec(
    name="DS-03 Colegio Grande",
    teachers=250,
    rooms=150,
    groups=150,
    subjects=15,
    load_factor=0.5,
)
XL = DatasetSpec(
    name="DS-XL Objetivo",
    teachers=500,
    rooms=300,
    groups=1500,
    subjects=20,
    # 1500 grupos con 300 aulas: la infraestructura manda. Con 0.20 la ocupación
    # de aulas daría exactamente el 100%, convirtiendo el problema en un
    # empaquetado perfecto (irreal y brutalmente difícil). 0.15 deja el ~71%,
    # que es la holgura con la que opera un colegio de verdad.
    load_factor=0.15,
)

PRESETS: dict[str, DatasetSpec] = {
    "small": SMALL,
    "medium": MEDIUM,
    "large": LARGE,
    "xl": XL,
}
