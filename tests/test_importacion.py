"""Alta masiva de datos maestros: leer tablas, importar, exportar, copiar y pegar.

Lo que se comprueba, de abajo arriba:

- `interop.tabular`: los tres delimitadores (`;`, `,`, tabulador), las tres
  codificaciones (utf-8, utf-8 con BOM y cp1252), el encabezado obligatorio y
  que nunca lanza por un dato malo.
- `application.untis.bulk`: encabezados en español, en alemán y con el nombre
  técnico del campo; alta frente a actualización; filas con errores (referencia
  inexistente, número mal escrito, id repetido, columna desconocida); que una
  fila con un error no deja nada escrito a medias; un único paso de deshacer;
  e ida y vuelta exportar-importar sin pérdidas en las seis cuadrículas.
- La interfaz (`MasterDataGrid`) con qtbot: pegar varias filas y columnas,
  importar un CSV de un archivo temporal y exportar.

Las pruebas trabajan sobre `_Servicio`, que es la Fachada tal cual (ya hereda
`BulkMixin`), para que se vea desde dónde lo usa la UI.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from scheduling_platform.application import MasterKind, UntisService, UntisSession
from scheduling_platform.application.untis.bulk import (
    column_map,
    import_master,
    normalize,
    preview_import,
    set_master_cells,
    table_from_rows,
)
from scheduling_platform.interop.tabular import read_table, write_table
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.widgets import master_grid
from untis_desktop.widgets.master_grid import MasterDataGrid


class _Servicio(UntisService):
    """La Fachada con el trozo de alta masiva ya heredado (será así en producción)."""


SVC = _Servicio()

#: Las seis cuadrículas, en orden de dependencia (lo apuntado antes que quien apunta).
TODAS = (
    MasterKind.DEPARTMENTS,
    MasterKind.ROOMS,
    MasterKind.SUBJECTS,
    MasterKind.CLASSES,
    MasterKind.TEACHERS,
    MasterKind.STUDENT_GROUPS,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _demo() -> UntisSession:
    """Proyecto pequeño con algo de cada cuadrícula y con referencias cruzadas."""
    s = SVC.new("Colegio Demo")
    import_master(s, MasterKind.DEPARTMENTS, "id;name\nCIE;Ciencias\nLET;Letras\n")
    import_master(
        s,
        MasterKind.ROOMS,
        "id;name;capacity;alternative_room;room_weight;department\n"
        "R1;Aula 1;30;R2;2;CIE\nR2;Aula 2;25;;0;LET\nLAB;Laboratorio;24;R1;4;CIE\n",
    )
    import_master(
        s,
        MasterKind.SUBJECTS,
        "id;name;main_subject;not_same_day;required_room;fore_color\n"
        "MAT;Matemáticas;x;x;;#112233\nFIS;Física;x;;LAB;\nMUS;Música;;;;\n",
    )
    import_master(
        s,
        MasterKind.CLASSES,
        "id;name;home_room;department;students;level;periods_per_day;text\n"
        "5A;Quinto A;R1;CIE;28;5;4-7;grupo mañana\n5B;Quinto B;R2;LET;26;5;;\n",
    )
    import_master(
        s,
        MasterKind.TEACHERS,
        "id;name;surname;forename;email;department;days_per_week_max;ntp_per_day;"
        "substitution_lock;text\n"
        "ANA;Ana Ruiz;Ruiz;Ana;ana@colegio.es;CIE;5;0-2;3;tutora\n"
        "BEA;Bea Gil;Gil;Bea;bea@colegio.es;LET;4;;0;\n",
    )
    import_master(
        s,
        MasterKind.STUDENT_GROUPS,
        "id;name;subject;classes;students\nG1;Grupo 1;MAT;5A, 5B;12\nG2;Grupo 2;MUS;5A;10\n",
    )
    # Sesión limpia: montar el proyecto de prueba no cuenta como paso de deshacer.
    return UntisSession(s.project)


@pytest.fixture
def demo() -> UntisSession:
    return _demo()


@pytest.fixture(autouse=True)
def _layout_aislado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """La disposición de columnas va a un .ini temporal, no al registro."""
    ini = str(tmp_path / "layout.ini")
    monkeypatch.setattr(
        master_grid, "layout_settings", lambda: QSettings(ini, QSettings.Format.IniFormat)
    )


@pytest.fixture
def bridge(qapp: QApplication) -> Iterator[FacadeBridge]:
    b = FacadeBridge(SVC)
    b.attach(_demo())
    qapp.processEvents()
    yield b
    b.set_language("es")


def _make[W: QWidget](qtbot: QtBot, widget: W) -> W:
    qtbot.addWidget(widget)
    return widget


def _grid(qtbot: QtBot, bridge: FacadeBridge, kind: MasterKind) -> MasterDataGrid:
    return _make(qtbot, MasterDataGrid(bridge, kind, kind.value))


def _col(grid: MasterDataGrid, field: str) -> int:
    return next(i for i, c in enumerate(grid.model.columns) if c.field == field)


def _ids(session: UntisSession, kind: MasterKind) -> list[str]:
    return [e.id for e in getattr(session.project, kind.value)]


# --------------------------------------------------------------------------- #
# interop.tabular: delimitadores, codificaciones y encabezado
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("sep", [";", ",", "\t"])
def test_los_tres_delimitadores_se_detectan_solos(sep: str) -> None:
    texto = f"id{sep}name\nR1{sep}Aula 1\nR2{sep}Aula 2\n"
    tabla = read_table(texto)
    assert tabla.delimiter == sep and tabla.ok
    assert tabla.headers == ("id", "name")
    assert [f.get("id") for f in tabla.rows] == ["R1", "R2"]
    assert tabla.rows[0].number == 1


@pytest.mark.parametrize("codificacion", ["utf-8", "utf-8-sig", "cp1252"])
def test_las_tres_codificaciones_se_detectan_solas(tmp_path: Path, codificacion: str) -> None:
    ruta = tmp_path / "aulas.csv"
    ruta.write_bytes("id;name\nR1;Música y Física\n".encode(codificacion))
    tabla = read_table(ruta)
    assert tabla.encoding == codificacion
    assert tabla.rows[0].get("name") == "Música y Física"


def test_el_encabezado_es_obligatorio_y_manda_en_el_delimitador() -> None:
    assert not read_table("").ok
    assert not read_table("   \n \n").ok
    # El delimitador sale del encabezado, no de los datos: aquí, tabulador.
    tabla = read_table("id\tname\nR1\tAula; con punto y coma\n")
    assert tabla.delimiter == "\t" and tabla.rows[0].get("name") == "Aula; con punto y coma"


def test_comillas_lineas_vacias_y_columnas_de_mas() -> None:
    tabla = read_table('id;name\n\n"R1";"Aula ""A"";grande"\nR2;Aula 2;sobra\n')
    assert tabla.rows[0].get("name") == 'Aula "A";grande'
    assert [f.get("id") for f in tabla.rows] == ["R1"]
    assert any("sobra" in e.message or "valores" in e.message for e in tabla.errors)
    assert tabla.errors[0].row == 2


def test_columna_repetida_y_encabezado_sin_nombre() -> None:
    tabla = read_table("id;name;name;\nR1;a;b;\n")
    assert tabla.headers == ("id", "name")
    assert any("repetida" in e.message for e in tabla.errors)


def test_leer_nunca_lanza_por_un_dato_malo(tmp_path: Path) -> None:
    assert not read_table(tmp_path / "no_existe.csv").ok
    assert not read_table(tmp_path).ok  # una carpeta tampoco lanza
    assert read_table("una sola columna\nvalor\n").ok


def test_escribir_entrecomilla_lo_necesario_y_vuelve_igual() -> None:
    texto = write_table(("id", "name"), (("R1", 'Aula "A"; grande'), ("R2", "")))
    assert texto.endswith("\r\n")
    assert read_table(texto).rows[0].get("name") == 'Aula "A"; grande'


# --------------------------------------------------------------------------- #
# Correspondencia entre nombre de columna y campo
# --------------------------------------------------------------------------- #


def test_el_nombre_de_columna_ignora_mayusculas_acentos_y_espacios() -> None:
    assert normalize(" Nombre  Corto ") == normalize("NOMBRE CORTO") == "nombrecorto"
    assert normalize("Períodos/día mín-máx") == "periodosdiaminmax"
    mapa = column_map(MasterKind.TEACHERS)
    for nombre in ("id", "Nombre corto", "KURZNAME", "nombre_corto"):
        assert mapa[normalize(nombre)].field == "id"
    assert mapa[normalize("Correo")].field == "email"
    assert mapa[normalize("E-Mail")].field == "email"


@pytest.mark.parametrize(
    "encabezado",
    [
        "id;name;capacity",
        "Nombre corto;Nombre completo;Capacidad",
        "Kurzname;Langname;Kapazität",
    ],
)
def test_encabezados_tecnicos_espanoles_y_alemanes(encabezado: str) -> None:
    s = SVC.new("X")
    informe = SVC.import_master(s, MasterKind.ROOMS, f"{encabezado}\nR1;Aula 1;30\n")
    assert informe.ok and informe.created == ("R1",)
    aula = s.project.rooms[0]
    assert (aula.id, aula.name, aula.capacity) == ("R1", "Aula 1", 30)


# --------------------------------------------------------------------------- #
# Alta, actualización y previsualización
# --------------------------------------------------------------------------- #


def test_alta_frente_a_actualizacion(demo: UntisSession) -> None:
    texto = "id;name;capacity\nR1;Aula Uno;33\nR9;Aula Nueva;20\n"
    previo = SVC.preview_import(demo, MasterKind.ROOMS, texto)
    assert previo.created == ("R9",) and previo.updated == ("R1",)
    assert not previo.applied and "R9" not in _ids(demo, MasterKind.ROOMS)

    informe = SVC.import_master(demo, MasterKind.ROOMS, texto)
    assert informe.applied and informe.created == ("R9",) and informe.updated == ("R1",)
    aulas = {a.id: a for a in demo.project.rooms}
    assert aulas["R1"].name == "Aula Uno" and aulas["R1"].capacity == 33
    assert aulas["R1"].alternative_room == "R2"  # columna que no venía: no se toca
    assert aulas["R9"].capacity == 20


def test_sin_actualizar_lo_existente_es_un_error(demo: UntisSession) -> None:
    informe = SVC.import_master(
        demo, MasterKind.ROOMS, "id;name\nR1;Otra\nR9;Nueva\n", update_existing=False
    )
    assert informe.created == ("R9",) and not informe.updated
    assert any("ya existe" in i.message for i in informe.issues)
    assert {a.id: a.name for a in demo.project.rooms}["R1"] == "Aula 1"


def test_una_fila_igual_no_cuenta_como_cambio(demo: UntisSession) -> None:
    antes = demo.project
    informe = SVC.import_master(demo, MasterKind.ROOMS, "id;name\nR1;Aula 1\n")
    assert informe.unchanged == ("R1",) and not informe.applied
    assert demo.project is antes and not demo.can_undo


def test_una_clase_nueva_se_lleva_la_primera_rejilla(demo: UntisSession) -> None:
    SVC.import_master(demo, MasterKind.CLASSES, "id;name\n6A;Sexto A\n")
    clase = next(c for c in demo.project.classes if c.id == "6A")
    assert clase.time_grid == demo.project.time_grids[0].id


def test_una_cadena_de_aulas_se_importa_de_una_vez() -> None:
    """La alternativa puede estar más abajo en el mismo archivo."""
    s = SVC.new("X")
    informe = SVC.import_master(s, MasterKind.ROOMS, "id;alternative_room\nA;B\nB;C\nC;\n")
    assert informe.ok and [r.alternative_room for r in s.project.rooms] == ["B", "C", None]


# --------------------------------------------------------------------------- #
# Filas con errores
# --------------------------------------------------------------------------- #


def test_referencia_inexistente_numero_malo_id_repetido_y_columna_desconocida(
    demo: UntisSession,
) -> None:
    texto = (
        "id;name;home_room;students;color favorito\n"
        "6A;Sexto A;R1;20;azul\n"
        "6B;Sexto B;NO_EXISTE;20;rojo\n"
        "6C;Sexto C;R2;muchos;verde\n"
        "6A;Repetida;R1;20;gris\n"
        ";Sin nombre corto;R1;20;\n"
    )
    informe = SVC.import_master(demo, MasterKind.CLASSES, texto)
    assert informe.created == ("6A",)
    assert informe.unknown_columns == ("color favorito",)
    motivos = " | ".join(i.render() for i in informe.issues)
    assert "Columna desconocida" in motivos
    assert "'NO_EXISTE' no existe" in motivos
    assert "dos veces" in motivos
    assert "nombre corto está vacío" in motivos
    assert {i.row for i in informe.issues if i.row} == {2, 3, 4, 5}
    assert informe.rows_failed == 4 and informe.rows_ok == 1
    # La columna desconocida se ignora, pero no impide que entre la fila buena.
    assert "6A" in _ids(demo, MasterKind.CLASSES)
    assert "6B" not in _ids(demo, MasterKind.CLASSES)


def test_una_fila_con_un_error_no_entra_a_medias(demo: UntisSession) -> None:
    """La columna buena de una fila mala tampoco se escribe."""
    informe = SVC.import_master(
        demo, MasterKind.ROOMS, "id;name;alternative_room\nR1;Nombre Nuevo;NO_EXISTE\n"
    )
    assert not informe.applied and not informe.ok
    assert {a.id: a.name for a in demo.project.rooms}["R1"] == "Aula 1"
    assert not demo.can_undo


def test_un_valor_fuera_de_rango_lo_para_la_entidad(demo: UntisSession) -> None:
    informe = SVC.import_master(demo, MasterKind.TEACHERS, "id;substitution_lock\nANA;99\n")
    assert not informe.applied
    assert any("0-9" in i.message for i in informe.issues)
    assert next(t for t in demo.project.teachers if t.id == "ANA").substitution_lock == 3


def test_estricto_no_aplica_nada_si_algo_falla(demo: UntisSession) -> None:
    texto = "id;name;home_room\n6A;Sexto A;R1\n6B;Sexto B;NO_EXISTE\n"
    informe = SVC.import_master(demo, MasterKind.CLASSES, texto, strict=True)
    assert not informe.applied and informe.created == ("6A",)
    assert "6A" not in _ids(demo, MasterKind.CLASSES) and not demo.can_undo


def test_sin_columna_de_nombre_corto_no_se_importa_nada(demo: UntisSession) -> None:
    informe = SVC.import_master(demo, MasterKind.ROOMS, "Nombre completo;Capacidad\nAula X;10\n")
    assert not informe.applied
    assert any("nombre corto" in i.message for i in informe.issues)


def test_lo_que_falta_se_resume_y_dice_que_hacer_antes(demo: UntisSession) -> None:
    """Caso real: exportar las clases de un colegio e importarlas en uno vacío.

    Fallan todas por lo mismo (rejillas y departamentos que no están); el
    informe lo resume en una línea y cada motivo dice dónde darlas de alta.
    """
    SVC.add_grid(demo, "Kinder")
    SVC.add_grid(demo, "Primaria")
    assert SVC.import_master(
        demo,
        MasterKind.CLASSES,
        "id;time_grid;department\nK1;Kinder;CIE\nK2;Kinder;LET\nP1;Primaria;CIE\n",
    ).ok
    csv = SVC.export_master(demo, MasterKind.CLASSES)

    vacio = SVC.new("Colegio Nuevo")
    previo = SVC.preview_import(vacio, MasterKind.CLASSES, csv)
    assert not previo.applied and previo.rows_failed == 5 and not previo.created
    assert dict(previo.missing) == {
        "time_grids": ("Kinder", "Primaria"),
        "departments": ("CIE", "LET"),
        "rooms": ("R1", "R2"),
    }
    resumen = previo.missing_summary()
    assert resumen.startswith("Faltan ") and resumen.endswith(".")
    assert "2 rejillas de tiempo: Kinder, Primaria" in resumen
    assert "2 departamentos: CIE, LET" in resumen and "2 aulas: R1, R2" in resumen
    assert resumen in previo.summary()

    motivos = " | ".join(i.message for i in previo.issues)
    assert "la rejilla 'Kinder' no existe: créala antes en Datos maestros -> Rejillas" in motivos
    assert "el departamento 'CIE' no existe: créalo antes en Datos maestros -> Departamentos" in (
        motivos
    )
    assert "el aula 'R1' no existe: créala antes en Datos maestros -> Aulas" in motivos
    # Lo mismo antes y después de aplicar.
    assert SVC.import_master(vacio, MasterKind.CLASSES, csv).missing == previo.missing


def test_los_motivos_de_referencia_dicen_donde_crearla(demo: UntisSession) -> None:
    resultado = SVC.set_master_cells(demo, MasterKind.CLASSES, [("5A", "home_room", "NO_EXISTE")])
    assert "el aula 'NO_EXISTE' no existe: créala antes en Datos maestros -> Aulas" in (
        resultado.summary()
    )
    informe = SVC.import_master(demo, MasterKind.TEACHERS, "id;department\nANA;NADA\n")
    assert "créalo antes en Datos maestros -> Departamentos" in informe.summary()
    assert dict(informe.missing) == {"departments": ("NADA",)}


def test_un_archivo_que_no_existe_no_lanza(demo: UntisSession, tmp_path: Path) -> None:
    informe = SVC.import_master(demo, MasterKind.ROOMS, tmp_path / "fantasma.csv")
    assert not informe.applied and not informe.ok


# --------------------------------------------------------------------------- #
# Un solo paso de deshacer
# --------------------------------------------------------------------------- #


def test_una_importacion_entera_es_un_solo_deshacer(demo: UntisSession) -> None:
    antes = demo.project
    filas = "\n".join(f"P{n:03d};Profesor {n};{n % 5 + 1}" for n in range(150))
    informe = SVC.import_master(demo, MasterKind.TEACHERS, f"id;name;days_per_week_max\n{filas}\n")
    assert informe.applied and len(informe.created) == 150
    assert len(demo.project.teachers) == 152
    assert "150" in demo.undo_label
    assert demo.undo()
    assert demo.project == antes and len(demo.project.teachers) == 2
    assert demo.redo() and len(demo.project.teachers) == 152


def test_escribir_varias_celdas_es_un_solo_deshacer(demo: UntisSession) -> None:
    antes = demo.project
    resultado = SVC.set_master_cells(
        demo,
        MasterKind.ROOMS,
        [("R1", "name", "Uno"), ("R1", "capacity", "40"), ("R2", "name", "Dos")],
    )
    assert resultado.ok and resultado.applied == 3
    aulas = {a.id: a for a in demo.project.rooms}
    assert (aulas["R1"].name, aulas["R1"].capacity, aulas["R2"].name) == ("Uno", 40, "Dos")
    assert demo.undo() and demo.project == antes


def test_las_celdas_malas_se_quedan_fuera_sin_tumbar_las_buenas(demo: UntisSession) -> None:
    resultado = set_master_cells(
        demo,
        MasterKind.ROOMS,
        [
            ("R1", "capacity", "40"),
            ("R1", "alternative_room", "NO_EXISTE"),
            ("R2", "capacity", "no es un número"),
            ("FANTASMA", "name", "x"),
        ],
    )
    assert resultado.applied == 1 and len(resultado.issues) == 3
    assert {i.field for i in resultado.issues} == {"alternative_room", "capacity", "name"}
    aulas = {a.id: a for a in demo.project.rooms}
    assert aulas["R1"].capacity == 40 and aulas["R1"].alternative_room == "R2"


# --------------------------------------------------------------------------- #
# Exportar e importar: ida y vuelta sin pérdidas
# --------------------------------------------------------------------------- #


def test_exportar_lleva_la_etiqueta_en_el_idioma_pedido(demo: UntisSession) -> None:
    es = SVC.export_master(demo, MasterKind.TEACHERS)
    de = SVC.export_master(demo, MasterKind.TEACHERS, language="de")
    assert es.splitlines()[0].startswith("Nombre corto;Nombre completo")
    assert de.splitlines()[0].startswith("Kurzname;Langname")
    assert len(es.splitlines()) == len(demo.project.teachers) + 1


@pytest.mark.parametrize("kind", TODAS)
@pytest.mark.parametrize("language", ["es", "de"])
def test_ida_y_vuelta_sin_perdidas_en_las_seis_cuadriculas(
    demo: UntisSession, kind: MasterKind, language: str
) -> None:
    """Exportar, importar en un proyecto vacío y obtener exactamente lo mismo."""
    destino = SVC.new("Copia")
    for previa in TODAS:  # las referencias tienen que existir antes
        if previa is kind:
            break
        SVC.import_master(destino, previa, SVC.export_master(demo, previa, language=language))
    informe = SVC.import_master(destino, kind, SVC.export_master(demo, kind, language=language))
    assert informe.ok, informe.summary()
    assert getattr(destino.project, kind.value) == getattr(demo.project, kind.value)


@pytest.mark.parametrize("kind", TODAS)
def test_reimportar_lo_exportado_no_cambia_nada(demo: UntisSession, kind: MasterKind) -> None:
    antes = demo.project
    informe = SVC.import_master(demo, kind, SVC.export_master(demo, kind))
    assert informe.ok and not informe.applied and not informe.created
    assert demo.project is antes and not demo.can_undo


def test_ida_y_vuelta_por_archivo_con_los_tres_delimitadores(
    demo: UntisSession, tmp_path: Path
) -> None:
    for sep in (";", ",", "\t"):
        ruta = tmp_path / f"aulas_{DELIM_NAMES[sep]}.csv"
        ruta.write_text(
            SVC.export_master(demo, MasterKind.ROOMS, delimiter=sep),
            encoding="utf-8-sig",
            newline="",
        )
        destino = SVC.new("Copia")
        assert SVC.import_master(destino, MasterKind.DEPARTMENTS, "id\nCIE\nLET\n").ok
        assert SVC.import_master(destino, MasterKind.ROOMS, ruta).ok
        assert destino.project.rooms == demo.project.rooms


#: Nombre de archivo legible para cada delimitador.
DELIM_NAMES = {";": "punto_y_coma", ",": "coma", "\t": "tabulador"}


# --------------------------------------------------------------------------- #
# Interfaz: pegar, importar y exportar
# --------------------------------------------------------------------------- #


def test_pegar_varias_filas_da_de_alta_en_un_solo_deshacer(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.ROOMS)
    antes = bridge.session.project
    grid.view.setCurrentIndex(grid.blank_index())
    bloque = "R7\tAula 7\t20\nR8\tAula 8\t22\n"
    assert grid.paste_text(bloque)
    qapp.processEvents()
    assert _ids(bridge.session, MasterKind.ROOMS)[-2:] == ["R7", "R8"]
    assert grid.message.kind == "ok" and "2 fila(s) nueva(s)" in grid.message.text()
    assert bridge.undo() and bridge.session.project == antes


def test_pegar_sobre_las_filas_que_hay_edita_varias_columnas(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.ROOMS)
    antes = bridge.session.project
    grid.view.setCurrentIndex(grid.proxy.index(0, _col(grid, "name")))
    assert grid.paste_text("Uno\t40\nDos\t41\n")
    qapp.processEvents()
    aulas = {a.id: a for a in bridge.session.project.rooms}
    assert (aulas["R1"].name, aulas["R1"].capacity) == ("Uno", 40)
    assert (aulas["R2"].name, aulas["R2"].capacity) == ("Dos", 41)
    assert bridge.undo() and bridge.session.project == antes


def test_pegar_un_valor_malo_pinta_la_celda_y_deja_pasar_el_resto(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.ROOMS)
    grid.view.setCurrentIndex(grid.proxy.index(0, _col(grid, "name")))
    assert not grid.paste_text("Uno\tmuchísimas\n")
    qapp.processEvents()
    assert {a.id: a for a in bridge.session.project.rooms}["R1"].name == "Uno"
    assert grid.model.error_at("R1", "capacity")
    assert grid.message.kind == "warning" and "rechazada" in grid.message.text()
    indice = grid.model.index(grid.model.row_of("R1"), _col(grid, "capacity"))
    assert indice.data(Qt.ItemDataRole.BackgroundRole) is not None


def test_pegar_mas_filas_de_las_que_hay_avisa(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.ROOMS)
    grid.view.setCurrentIndex(grid.proxy.index(2, _col(grid, "name")))
    assert not grid.paste_text("Uno\nDos\nTres\n")
    qapp.processEvents()
    assert "no cabían" in grid.message.text()


def test_copiar_y_pegar_entre_cuadriculas_del_mismo_tipo(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.DEPARTMENTS)
    grid.view.selectAll()
    texto = grid.copy_selection()
    assert texto.splitlines() == ["CIE\tCiencias", "LET\tLetras"]
    assert QGuiApplication.clipboard().text() == texto

    bridge.attach(SVC.new("Otro"))
    qapp.processEvents()
    otra = _grid(qtbot, bridge, MasterKind.DEPARTMENTS)
    otra.view.setCurrentIndex(otra.blank_index())
    assert otra.paste_clipboard()
    qapp.processEvents()
    assert _ids(bridge.session, MasterKind.DEPARTMENTS) == ["CIE", "LET"]


def test_pegar_respeta_las_columnas_ocultas_y_su_orden(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.ROOMS)
    grid.set_column_hidden(_col(grid, "name"), True)
    assert _col(grid, "name") not in grid.visible_columns()
    grid.view.setCurrentIndex(grid.blank_index())
    assert grid.paste_text("R7\t44\n")  # sin "Nombre completo": el siguiente es Capacidad
    qapp.processEvents()
    aula = next(a for a in bridge.session.project.rooms if a.id == "R7")
    assert (aula.name, aula.capacity) == ("", 44)


def test_importar_csv_desde_un_archivo_temporal(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication, tmp_path: Path
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.TEACHERS)
    ruta = tmp_path / "profesores.csv"
    ruta.write_bytes(
        "Nombre corto;Nombre completo;Correo\nCARLOS;Carlos Pérez;c@colegio.es\n".encode("cp1252")
    )
    informe = grid.import_csv(ruta)
    qapp.processEvents()
    assert informe is not None and informe.ok and informe.created == ("CARLOS",)
    profe = next(t for t in bridge.session.project.teachers if t.id == "CARLOS")
    assert (profe.name, profe.email) == ("Carlos Pérez", "c@colegio.es")
    assert grid.model.row_of("CARLOS") >= 0 and grid.message.kind == "ok"


def test_importar_un_csv_con_errores_dice_cuantas_entraron_y_cuales_no(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication, tmp_path: Path
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.CLASSES)
    ruta = tmp_path / "clases.csv"
    ruta.write_text("id,name,home_room\n6A,Sexto A,R1\n6B,Sexto B,NO_EXISTE\n", encoding="utf-8")
    informe = grid.import_csv(ruta)
    qapp.processEvents()
    assert informe is not None and informe.created == ("6A",) and informe.rows_failed == 1
    assert grid.message.kind == "warning"
    assert "1 fila(s) nueva(s)" in grid.message.text()
    assert "NO_EXISTE" in grid.message.text() and "fila 2" in grid.message.text()


def test_exportar_csv_y_volver_a_importarlo_desde_la_interfaz(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication, tmp_path: Path
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.SUBJECTS)
    destino = grid.export_csv(tmp_path / "materias")
    assert destino is not None and destino.name == "materias.csv"
    assert destino.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM: Excel abre las tildes bien
    assert grid.message.kind == "ok" and "3 fila(s)" in grid.message.text()

    antes = bridge.session.project.subjects
    bridge.attach(SVC.new("Otro"))
    qapp.processEvents()
    otra = _grid(qtbot, bridge, MasterKind.SUBJECTS)
    assert SVC.import_master(bridge.session, MasterKind.ROOMS, "id\nLAB\n").ok
    informe = otra.import_csv(destino)
    assert informe is not None and informe.ok
    assert bridge.session.project.subjects == antes


def test_los_botones_nuevos_llevan_icono_y_ayuda_y_se_activan(
    qtbot: QtBot, bridge: FacadeBridge, qapp: QApplication
) -> None:
    grid = _grid(qtbot, bridge, MasterKind.ROOMS)
    for boton in (grid.copy_button, grid.paste_button, grid.import_button, grid.export_button):
        assert not boton.icon().isNull()
        assert len(boton.toolTip()) > 20 and boton.text()
    for boton in (grid.paste_button, grid.import_button, grid.export_button):
        assert boton.isEnabled()
    assert not grid.copy_button.isEnabled()  # sin fila elegida no hay nada que copiar
    grid.select_key("R1")
    assert grid.copy_button.isEnabled()
    textos = {a.text() for a in grid.row_menu().actions() if not a.isSeparator()}
    assert {"Copiar", "Pegar", "Importar CSV...", "Exportar CSV..."} <= textos
    bridge.set_language("de")
    assert grid.import_button.text()

    sin_proyecto = _make(qtbot, MasterDataGrid(FacadeBridge(SVC), MasterKind.ROOMS, "vacia"))
    assert not sin_proyecto.import_button.isEnabled()
    assert sin_proyecto.import_csv("x.csv") is None
    assert sin_proyecto.export_csv("x.csv") is None


def test_la_tabla_de_un_bloque_pegado_usa_los_campos_como_encabezado() -> None:
    tabla = table_from_rows(["id", "name"], [["R1", " Aula 1 "], ["R2"]])
    assert tabla.headers == ("id", "name")
    assert tabla.rows[0].get("name") == "Aula 1" and tabla.rows[1].get("name") == ""
    s = SVC.new("X")
    assert preview_import(s, MasterKind.ROOMS, tabla).created == ("R1", "R2")
