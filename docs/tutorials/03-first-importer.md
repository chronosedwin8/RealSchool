# Tutorial 3 — Tu primer importador

Leeremos un CSV mínimo y lo traduciremos al Modelo Canónico reutilizando el
adaptador académico (concepto en [Guía: importadores](../sdk_guide/importers.md)).

## El CSV

Una fila por carga académica: docente, materia, grupo y número de sesiones
semanales.

```text
teacher,subject,group,sessions
0,0,0,2
```

## El importador (ejecutable)

Construimos un `AcademicProblem` desde el CSV, lo pasamos por
`AcademicToCanonicalAdapter` y lo guardamos en un `.bjs`. La integridad
referencial (IDs válidos) se valida sola al construir el `AcademicProblem`:

```python
import csv
import io
import tempfile
from pathlib import Path

from scheduling_platform.academic import (
    AcademicProblem, AcademicToCanonicalAdapter,
    Teacher, Room, StudentGroup, Subject, TeachingAssignment, TimeFrame,
)
from scheduling_platform.academic.ids import (
    TeacherId, RoomId, GroupId, SubjectId, AssignmentId,
)
from scheduling_platform.application import new_project, open_project

CSV = "teacher,subject,group,sessions\n0,0,0,2\n"

rows = list(csv.DictReader(io.StringIO(CSV)))
academic = AcademicProblem(
    time_frame=TimeFrame(("Lun", "Mar", "Mié", "Jue", "Vie"), periods_per_day=7),
    rooms=(Room(RoomId(0), "Aula 1", capacity=30),),
    teachers=(Teacher(TeacherId(0), "Docente A"),),
    groups=(StudentGroup(GroupId(0), "10A", size=26),),
    subjects=(Subject(SubjectId(0), "Matemáticas"),),
    assignments=tuple(
        TeachingAssignment(
            AssignmentId(i),
            TeacherId(int(r["teacher"])),
            SubjectId(int(r["subject"])),
            GroupId(int(r["group"])),
            session_lengths=(1,) * int(r["sessions"]),
        )
        for i, r in enumerate(rows)
    ),
)

problem = AcademicToCanonicalAdapter().translate(academic).problem
assert len(problem.tasks) == 2  # dos sesiones semanales -> dos tareas canónicas

# guardar en un .bjs y releerlo
with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "colegio.bjs"
    new_project(path, "Mi Colegio", problem)
    assert open_project(path).problem.horizon == problem.horizon
```

A partir de aquí, `schedule-engine optimize colegio.bjs` resuelve el horario.

**Siguiente:** [publicar plugins](04-publishing-plugins.md).
