"""Pruebas de `interop.gpu`: lectura y escritura de los archivos GPU de Untis.

El test de aceptación es la ida y vuelta `proyecto → write_gpu → read_gpu`,
comparando campo a campo todo lo que GPU puede transportar (`carried`).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from scheduling_platform.interop.gpu import (
    GPU001_COLUMNS,
    GPU002_COLUMNS,
    GPU007_COLUMNS,
    GPU_TIMETABLE_ID,
    _read_lessons,
    _read_timetable,
    decode_gpu,
    parse_gpu,
    read_gpu,
    read_gpu001,
    read_gpu002,
    read_gpu016,
    render_gpu,
    select_timetable,
    sniff_delimiter,
    write_gpu,
    write_gpu001,
    write_gpu_file,
)
from scheduling_platform.untis_model import (
    UNSET,
    Assignment,
    Department,
    EntityKind,
    Evaluation,
    Lesson,
    LessonLine,
    MinMax,
    PeriodDef,
    Room,
    SchoolClass,
    SchoolInfo,
    StudentGroup,
    Subject,
    Teacher,
    Term,
    TimeGrid,
    TimeRequest,
    Timetable,
    UntisProject,
    Weighting,
)

# --------------------------------------------------------------------------- #
# Proyecto sintético
# --------------------------------------------------------------------------- #


def _grid(ident: str, periods: int) -> TimeGrid:
    return TimeGrid(
        id=ident,
        name=f"Rejilla {ident}",
        periods=tuple(
            PeriodDef(number=n, start=420 + 50 * n, end=465 + 50 * n) for n in range(1, periods + 1)
        ),
    )


def synthetic_project() -> UntisProject:
    """Proyecto pequeño con todo lo que GPU debe transportar (y algo que no)."""
    return UntisProject(
        school=SchoolInfo(name="Colegio de prueba"),
        time_grids=(_grid("PRI", 6), _grid("SEC", 8)),
        departments=(
            Department("CIE", "Ciencias"),
            Department("LEN", 'Lenguas, "idiomas"'),
        ),
        classes=(
            SchoolClass(
                id="5A",
                name="Quinto A",
                time_grid="PRI",
                home_room="R1",
                department="CIE",
                students=28,
                level=5,
                periods_per_day=MinMax(4, 7),
                lunch_break=MinMax(1, 2),
                main_subjects_per_day=3,
                main_subjects_consecutive=2,
                text="Grupo bilingüe",
            ),
            SchoolClass(id="5B", name="Quinto B", time_grid="SEC"),
        ),
        teachers=(
            Teacher(
                id="MUE",
                name="Sr. Müller",
                surname="Müller",
                forename="José",
                email="mue@example.org",
                department="LEN",
                home_room="R2",
                periods_per_day=MinMax(2, 6),
                days_per_week_max=4,
                ntp_per_day=MinMax(0, 2),
                ntp_per_week=MinMax(1, 5),
                lunch_break=MinMax(None, 1),
                consecutive_max=4,
                text="Tutor",
                status="Docente,",
                payroll_number="0042",
                gender="M",
            ),
            Teacher(id="GAR", surname="García, Peña", forename="Ana"),
            Teacher(id="PER", surname="Pérez"),
        ),
        rooms=(
            Room(
                id="R1",
                name="Aula 1",
                capacity=30,
                alternative_room="R2",
                room_weight=2,
                department="CIE",
                text="Planta 1",
            ),
            Room(id="R2", name="Laboratorio", room_weight=4),
        ),
        subjects=(
            Subject(
                id="MA",
                name="Matemáticas",
                main_subject=True,
                not_same_day=True,
                fore_color="0",
                back_color="16744448",
            ),
            Subject(
                id="SP",
                name="Deporte",
                double_period_required=True,
                required_room="R2",
                subject_group="GIM",
                fore_color="#000000",
                back_color="#FF8040",
            ),
            Subject(id="EN", name="Inglés"),
            Subject(id="D", name="Alemán", main_subject=True, double_period_required=True),
        ),
        student_groups=(StudentGroup(id="EN1", subject="EN", classes=("5A",)),),
        terms=(Term(id="T1", begin="20260801", end="20261130"),),
        lessons=(
            Lesson(
                number=1,
                lines=(
                    LessonLine(
                        subject="MA",
                        teacher="MUE",
                        classes=("5A",),
                        room="R1",
                        alternative_room="R2",
                        weekly_value=1.5,
                    ),
                ),
                periods_per_week=4,
                time_grid="PRI",
                double_periods=MinMax(1, 2),
                block=(2,),
                fixed=True,
                not_same_day=True,
                weekly_value=4.0,
                term="T1",
                effective_begin="20260801",
                effective_end="20261130",
                occurrence="11111FF",
            ),
            Lesson(
                number=2,
                lines=(
                    LessonLine(
                        subject="EN",
                        teacher="MUE",
                        classes=("5A", "5B"),
                        student_group="EN1",
                        room="R1",
                        weekly_value=0.75,
                    ),
                    LessonLine(subject="EN", teacher="GAR", classes=("5A", "5B"), room="R2"),
                    LessonLine(subject="EN", teacher="PER", classes=("5A", "5B")),
                ),
                periods_per_week=3,
                lesson_group="LG1",
                sequence_after="MA",
            ),
            Lesson(
                number=3,
                lines=(LessonLine(subject="SP", teacher=None, classes=("5B",)),),
                periods_per_week=2,
                block=(2, 2),
                ignore=True,
            ),
            Lesson(
                number=40,
                lines=(LessonLine(subject="D", teacher="GAR"),),
                periods_per_week=1,
                double_periods=MinMax(None, 0),
            ),
            # Acople con dos líneas sin profesor y la misma materia: solo las
            # distingue "Wochenstd. Le." y el cambio de clase.
            Lesson(
                number=41,
                lines=(
                    LessonLine(subject="SP", classes=("5A",)),
                    LessonLine(subject="SP", classes=("5B",)),
                ),
                periods_per_week=2,
                block=(3, 2, 2),
            ),
        ),
        time_requests=(
            TimeRequest(EntityKind.TEACHER, "MUE", -3, day=1, period=1),
            TimeRequest(EntityKind.CLASS, "5A", 2, day=2, period=3),
            TimeRequest(EntityKind.ROOM, "R1", 3, day=5),
            TimeRequest(EntityKind.SUBJECT, "MA", -1, period=6),
            TimeRequest(EntityKind.STUDENT_GROUP, "EN1", -2, day=1, period=2),
        ),
        weighting=Weighting(),
        timetables=(
            Timetable(id="viejo", assignments=(Assignment(1, 0, 3, 3),)),
            Timetable(
                id="untis",
                name="Horario final",
                assignments=(
                    Assignment(1, 0, 1, 1, room="R1", fixed=True),
                    Assignment(1, 0, 2, 3, room="R1", manual=True),
                    Assignment(2, 0, 3, 2, room="R1"),
                    Assignment(2, 1, 3, 2, room="R2"),
                    Assignment(2, 2, 3, 2),
                    Assignment(3, 0, 4, 5, room="R2"),
                    Assignment(40, 0, 5, 1),
                    Assignment(41, 0, 5, 2),
                    Assignment(41, 1, 5, 2),
                ),
                evaluation=Evaluation(unplaced_periods=3),
            ),
        ),
    )


def carried(project: UntisProject, timetable_id: str | None = None) -> UntisProject:
    """Proyección de `project` sobre los campos que GPU transporta.

    Lo que GPU no lleva vuelve a su valor neutro, que es lo que devuelve
    `read_gpu`; así la ida y vuelta se compara con igualdad de dataclasses.
    """
    horario = select_timetable(project, timetable_id)
    return UntisProject(
        departments=project.departments,
        classes=tuple(replace(c, time_grid="", students=0) for c in project.classes),
        teachers=tuple(
            replace(t, name="", ntp_per_day=UNSET, days_per_week_max=None) for t in project.teachers
        ),
        rooms=project.rooms,
        subjects=tuple(replace(s, not_same_day=False) for s in project.subjects),
        lessons=tuple(
            replace(
                le,
                lines=tuple(
                    replace(ln, alternative_room=None, weekly_value=round(ln.weekly_value, 5))
                    for ln in le.lines
                ),
                time_grid="",
                block=le.block[:3],
                not_same_day=False,
                sequence_after=None,
                weekly_value=0.0,
                term=None,
                occurrence="",
            )
            for le in project.lessons
        ),
        time_requests=tuple(
            r for r in project.time_requests if r.entity_kind is not EntityKind.STUDENT_GROUP
        ),
        timetables=(
            ()
            if horario is None
            else (
                Timetable(
                    id=GPU_TIMETABLE_ID,
                    assignments=tuple(
                        replace(a, fixed=False, manual=False) for a in horario.assignments
                    ),
                ),
            )
        ),
    )


# --------------------------------------------------------------------------- #
# Ida y vuelta
# --------------------------------------------------------------------------- #


def test_round_trip_synthetic(tmp_path: Path) -> None:
    proyecto = synthetic_project()
    rutas = write_gpu(proyecto, tmp_path)
    assert sorted(p.name for p in rutas) == [
        "GPU001.TXT",
        "GPU002.TXT",
        "GPU003.TXT",
        "GPU004.TXT",
        "GPU005.TXT",
        "GPU006.TXT",
        "GPU007.TXT",
        "GPU016.TXT",
    ]
    leido = read_gpu(tmp_path)
    esperado = carried(proyecto)
    assert leido.departments == esperado.departments
    assert leido.classes == esperado.classes
    assert leido.teachers == esperado.teachers
    assert leido.rooms == esperado.rooms
    assert leido.subjects == esperado.subjects
    assert leido.lessons == esperado.lessons
    assert leido.time_requests == esperado.time_requests
    assert leido.timetables == esperado.timetables
    assert leido == esperado


def test_coupled_lesson_keeps_three_lines(tmp_path: Path) -> None:
    write_gpu(synthetic_project(), tmp_path)
    leccion = next(le for le in read_gpu002(tmp_path / "GPU002.TXT") if le.number == 2)
    assert leccion.is_coupled
    assert [ln.teacher for ln in leccion.lines] == ["MUE", "GAR", "PER"]
    assert all(ln.classes == ("5A", "5B") for ln in leccion.lines)
    # Una fila por (línea, clase): 3 líneas x 2 clases.
    filas = (tmp_path / "GPU002.TXT").read_text("cp1252").splitlines()
    assert sum(1 for f in filas if f.startswith("2,")) == 6


def test_round_trip_selected_timetable(tmp_path: Path) -> None:
    proyecto = synthetic_project()
    write_gpu(proyecto, tmp_path, timetable_id="viejo")
    assert read_gpu(tmp_path) == carried(proyecto, "viejo")


def test_write_without_timetable_skips_gpu001(tmp_path: Path) -> None:
    proyecto = replace(synthetic_project(), timetables=())
    rutas = write_gpu(proyecto, tmp_path)
    assert "GPU001.TXT" not in {p.name for p in rutas}
    assert read_gpu(tmp_path).timetables == ()
    with pytest.raises(ValueError, match="horario"):
        write_gpu(proyecto, tmp_path, timetable_id="nada")


def test_read_empty_directory(tmp_path: Path) -> None:
    assert read_gpu(tmp_path) == UntisProject()
    with pytest.raises(NotADirectoryError):
        read_gpu(tmp_path / "no_existe")


def test_round_trip_anon_xml(anon_xml_path: Path, tmp_path: Path) -> None:
    """`xml → gpu → untis_model` sobre el export real seudonimizado."""
    xml = pytest.importorskip("scheduling_platform.interop.xml")
    proyecto: UntisProject = xml.read_xml(anon_xml_path)
    write_gpu(proyecto, tmp_path)
    leido = read_gpu(tmp_path)
    esperado = carried(proyecto)
    assert leido.departments == esperado.departments
    assert leido.classes == esperado.classes
    assert leido.teachers == esperado.teachers
    assert leido.rooms == esperado.rooms
    assert leido.subjects == esperado.subjects
    assert len(leido.lessons) == len(esperado.lessons)
    for real, esp in zip(leido.lessons, esperado.lessons, strict=True):
        assert real == esp, esp.number
    assert leido.time_requests == esperado.time_requests
    assert leido.timetables == esperado.timetables


# --------------------------------------------------------------------------- #
# GPU001: contrato con MiUntisWeb
# --------------------------------------------------------------------------- #


def test_gpu001_golden(tmp_path: Path) -> None:
    proyecto = UntisProject(
        lessons=(
            Lesson(
                number=7,
                lines=(LessonLine(subject="MA", teacher="MÜL", classes=("5A", "5B"), room="R9"),),
                periods_per_week=1,
            ),
            Lesson(number=8, lines=(LessonLine(subject="SP"),), periods_per_week=1),
        ),
        timetables=(
            Timetable(
                id="t",
                assignments=(Assignment(7, 0, 1, 2, room="R1"), Assignment(8, 0, 2, 1)),
            ),
        ),
    )
    ruta = write_gpu001(proyecto, tmp_path / "GPU001.TXT")
    assert ruta.read_bytes() == (
        b'7,"5A","M\xdcL","MA","R1",1,2,,\r\n7,"5B","M\xdcL","MA","R1",1,2,,\r\n8,,,"SP",,2,1,,\r\n'
    )
    horario = read_gpu001(ruta, proyecto.lessons)
    assert horario.assignments == (Assignment(7, 0, 1, 2, room="R1"), Assignment(8, 0, 2, 1))


def test_gpu001_enbrea_sample_without_lessons() -> None:
    """Filas de ejemplo de Enbrea (`TestGpuLessonTime`), sin GPU002 al lado."""
    texto = (
        '3969,"2.T1 + L","SteIn","RLK","KL14",3,4,,\r\n1055,"5AG","LenPh","F","AWR -DirTr.",1,1,,'
    )
    horario = _read_timetable(parse_gpu(texto, GPU001_COLUMNS), ())
    assert horario.assignments == (
        Assignment(3969, 0, 3, 4, room="KL14"),
        Assignment(1055, 0, 1, 1, room="AWR -DirTr."),
    )


def test_gpu001_rows_with_several_classes_collapse(tmp_path: Path) -> None:
    ruta = tmp_path / "GPU001.TXT"
    ruta.write_bytes(
        b'5,"1a","ABC","D","R1",1,1,,\r\n'
        b'5,"1b","ABC","D","R1",1,1,,\r\n'
        b'5,"1a","XYZ","D",,1,1,,\r\n'
        b'5,"1a","ABC","D","R1",2,3,,\r\n'
    )
    horario = read_gpu001(ruta)
    assert horario.assignments == (
        Assignment(5, 0, 1, 1, room="R1"),
        Assignment(5, 1, 1, 1),
        Assignment(5, 0, 2, 3, room="R1"),
    )


# --------------------------------------------------------------------------- #
# Codificación y tolerancia
# --------------------------------------------------------------------------- #


def test_write_cp1252_and_read_back(tmp_path: Path) -> None:
    proyecto = UntisProject(
        departments=(Department("ESP", "Español: á ñ ü"),),
        teachers=(Teacher(id="NUN", surname="Núñez", forename="Begoña"),),
    )
    write_gpu(proyecto, tmp_path)
    crudo = (tmp_path / "GPU007.TXT").read_bytes()
    assert crudo == b'"ESP","Espa\xf1ol: \xe1 \xf1 \xfc"\r\n'
    leido = read_gpu(tmp_path)
    assert leido.departments == proyecto.departments
    assert leido.teachers == proyecto.teachers


def test_write_utf8_configurable(tmp_path: Path) -> None:
    proyecto = UntisProject(departments=(Department("X", "Łódź ő"),))
    # En cp1252 no cabe "Łő": por defecto no falla, se escribe "?" (como Windows).
    write_gpu(proyecto, tmp_path)
    assert (tmp_path / "GPU007.TXT").read_bytes() == '"X","?ód? ?"\r\n'.encode("cp1252")
    with pytest.raises(UnicodeEncodeError):
        write_gpu_file(tmp_path / "estricto.txt", [["Łódź"]], errors="strict")
    write_gpu(proyecto, tmp_path, encoding="utf-8")
    assert (tmp_path / "GPU007.TXT").read_bytes() == '"X","Łódź ő"\r\n'.encode()
    assert read_gpu(tmp_path).departments == proyecto.departments


@pytest.mark.parametrize(
    "data",
    [
        b'\xef\xbb\xbf"5A","Se\xc3\xb1or \xc3\xa1\xc3\xbc"\r\n',  # UTF-8 con BOM
        b'"5A","Se\xc3\xb1or \xc3\xa1\xc3\xbc"\r\n',  # UTF-8 sin BOM
        b'"5A","Se\xf1or \xe1\xfc"\r\n',  # Windows-1252
    ],
    ids=["utf8-bom", "utf8", "cp1252"],
)
def test_read_tolerant_encodings(tmp_path: Path, data: bytes) -> None:
    (tmp_path / "GPU003.TXT").write_bytes(data)
    clases = read_gpu(tmp_path).classes
    assert clases == (SchoolClass(id="5A", name="Señor áü"),)


def test_decode_gpu_policy() -> None:
    assert decode_gpu(b"\xef\xbb\xbfabc") == "abc"
    assert decode_gpu("ñ".encode("utf-16")) == "ñ"
    assert decode_gpu(b"\xc3\xb1") == "ñ"
    assert decode_gpu(b"\xf1") == "ñ"


def test_semicolon_and_tab_delimited_input(tmp_path: Path) -> None:
    (tmp_path / "GPU004.TXT").write_bytes(
        b'"MUE";"M\xfcller, Hans";;;"R1";;;2;6\r\n"GAR";"Garc\xeda"\r\n'
    )
    (tmp_path / "GPU016.TXT").write_bytes(b'"L"\t"MUE"\t1\t2\t-3\r\n')
    leido = read_gpu(tmp_path)
    assert leido.teachers == (
        Teacher(id="MUE", surname="Müller, Hans", home_room="R1", periods_per_day=MinMax(2, 6)),
        Teacher(id="GAR", surname="García"),
    )
    assert leido.time_requests == (TimeRequest(EntityKind.TEACHER, "MUE", -3, day=1, period=2),)


def test_sniff_delimiter() -> None:
    assert sniff_delimiter('"a;b","c"\r\n') == ","
    assert sniff_delimiter('\r\n"a,b";"c";1\r\n') == ";"
    assert sniff_delimiter("a\tb\r\n") == "\t"
    assert sniff_delimiter("") == ","


def test_short_and_long_rows_do_not_crash(tmp_path: Path) -> None:
    (tmp_path / "GPU003.TXT").write_bytes(b'"5A"\r\n\r\n"5B","B",,"R1",,,x,9\r\n')
    (tmp_path / "GPU005.TXT").write_bytes(b'"R1","Aula",,,,,9,-4,,,,,,,,,,,,extra,extra\r\n')
    (tmp_path / "GPU002.TXT").write_bytes(b'1,2\r\n2,1,1,1,"5A","MUE","MA"\r\nx,1\r\n')
    (tmp_path / "GPU001.TXT").write_bytes(b'2,"5A","MUE","MA"\r\n2,"5A","MUE","MA",,1,1\r\n')
    (tmp_path / "GPU016.TXT").write_bytes(b'"L","MUE",1\r\n"K","5A",0,0,-3\r\n"Z","?",1,1,1\r\n')
    leido = read_gpu(tmp_path)
    assert leido.classes == (
        SchoolClass(id="5A"),
        SchoolClass(id="5B", name="B", home_room="R1", periods_per_day=MinMax(None, 9)),
    )
    assert leido.rooms == (Room(id="R1", name="Aula", room_weight=4),)
    assert leido.lessons == (
        Lesson(
            number=2,
            lines=(LessonLine(subject="MA", teacher="MUE", classes=("5A",)),),
            periods_per_week=1,
        ),
    )
    assert leido.timetables[0].assignments == (Assignment(2, 0, 1, 1),)
    assert leido.time_requests == ()


def test_gpu016_zero_means_whole_day_or_period(tmp_path: Path) -> None:
    ruta = tmp_path / "GPU016.TXT"
    ruta.write_bytes(b'"R","R1",3,0,2\r\n"F","MA",0,4,-2\r\n"K","5A",1,1,0\r\n"L","X",1,1,7\r\n')
    assert read_gpu016(ruta) == (
        TimeRequest(EntityKind.ROOM, "R1", 2, day=3),
        TimeRequest(EntityKind.SUBJECT, "MA", -2, period=4),
    )


def test_gpu002_untis_style_rows() -> None:
    """Filas al estilo Untis: dos profesores sobre dos clases y sin "Wochenstd. Le."."""
    texto = (
        '9,2,2,2,"1a","AAA","D","R1~R2",,0,2.00000\r\n'
        '9,2,2,0,"1b","AAA","D","R1"\r\n'
        '9,2,0,0,"1a","BBB","D"\r\n'
        '9,2,0,0,"1b","BBB","D"\r\n'
        '362,2,,2,,"EinAl","SA",,,0,2.00000,,,,"20080901","20090704",0.00800,,,,,,,"In"\r\n'
    )
    lecciones = _read_lessons(parse_gpu(texto, GPU002_COLUMNS))
    assert lecciones[0] == Lesson(
        number=9,
        lines=(
            LessonLine(
                subject="D", teacher="AAA", classes=("1a", "1b"), room="R1", weekly_value=2.0
            ),
            LessonLine(subject="D", teacher="BBB", classes=("1a", "1b")),
        ),
        periods_per_week=2,
    )
    # Ejemplo de Enbrea (`TestGpuLesson`): el Kennzeichen distingue mayúsculas,
    # así que "In" no contiene la marca "i" (ignorar).
    assert lecciones[1] == Lesson(
        number=362,
        lines=(LessonLine(subject="SA", teacher="EinAl", weekly_value=2.0),),
        periods_per_week=2,
        effective_begin="20080901",
        effective_end="20090704",
    )


# --------------------------------------------------------------------------- #
# Propiedades
# --------------------------------------------------------------------------- #

_SAFE = st.characters(blacklist_categories=("Cc", "Cs", "Zl", "Zp"))
_TEXT = st.text(_SAFE, max_size=20).map(str.strip)
_ID = _TEXT.filter(bool)
_CP1252_TEXT = st.text(
    st.characters(codec="cp1252", blacklist_categories=("Cc", "Cs")), max_size=20
).map(str.strip)


@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    departments=st.lists(
        st.builds(Department, id=_ID, name=_TEXT), max_size=5, unique_by=lambda d: d.id
    ),
    surname=_TEXT,
    forename=_TEXT,
    subject=_ID,
    teacher=_ID,
)
def test_text_fields_survive_quoting(
    tmp_path: Path,
    departments: list[Department],
    surname: str,
    forename: str,
    subject: str,
    teacher: str,
) -> None:
    """Comas, comillas, punto y coma y cualquier Unicode sobreviven (UTF-8)."""
    proyecto = UntisProject(
        departments=tuple(departments),
        teachers=(Teacher(id=teacher, surname=surname, forename=forename),),
        subjects=(Subject(id=subject),),
        lessons=(
            Lesson(
                number=1,
                lines=(LessonLine(subject=subject, teacher=teacher, classes=(subject,)),),
                periods_per_week=1,
            ),
        ),
        timetables=(
            Timetable(id="t", assignments=(Assignment(1, 0, 1, 1, room=surname or None),)),
        ),
    )
    write_gpu(proyecto, tmp_path, encoding="utf-8")
    assert read_gpu(tmp_path) == carried(proyecto)


@settings(max_examples=60)
@given(rows=st.lists(st.lists(st.one_of(_CP1252_TEXT, st.integers(-5, 5000)), min_size=2)))
def test_render_parse_cp1252_property(rows: list[list[str | int]]) -> None:
    """`render_gpu` + codificación cp1252 preservan cada celda (comillas incluidas)."""
    texto = render_gpu(rows).encode("cp1252").decode("cp1252")
    leidas = [fila.values for fila in parse_gpu(texto, GPU007_COLUMNS)]
    esperadas = [tuple(str(v) for v in fila) for fila in rows if any(str(v) for v in fila)]
    assert [tuple(v.strip() for v in fila) for fila in leidas] == esperadas


def test_new_master_data_columns(tmp_path: Path) -> None:
    """Texto, estado, nº de personal, género, colores y vigencia viajan por GPU."""
    write_gpu(synthetic_project(), tmp_path)
    leido = read_gpu(tmp_path)
    assert leido.class_by_id["5A"].text == "Grupo bilingüe"
    profe = leido.teacher_by_id["MUE"]
    assert (profe.text, profe.status, profe.payroll_number, profe.gender) == (
        "Tutor",
        "Docente,",
        "0042",
        "M",
    )
    assert leido.room_by_id["R1"].text == "Planta 1"
    assert (leido.subject_by_id["MA"].fore_color, leido.subject_by_id["MA"].back_color) == (
        "0",
        "16744448",
    )
    assert leido.subject_by_id["SP"].back_color == "#FF8040"
    le = leido.lesson_by_number[1]
    assert (le.effective_begin, le.effective_end, le.occurrence) == ("20260801", "20261130", "")
    # El color decimal de Untis se escribe como número, sin comillas.
    fila_ma = next(
        f
        for f in (tmp_path / "GPU006.TXT").read_text("cp1252").splitlines()
        if f.startswith('"MA"')
    )
    assert ",0,16744448," in fila_ma
