"""Alta masiva de datos maestros: importar y exportar cuadrículas enteras.

Un colegio real tiene 150 profesores y 900 lecciones: darlos de alta fila a fila
no es una opción. Aquí vive el caso de uso "mete tus datos de golpe":

- `export_master`: la cuadrícula entera como CSV, con la etiqueta de columna en
  el idioma que se pida, para abrirla en Excel.
- `preview_import`: qué se crearía, qué se actualizaría y qué está mal, **sin
  tocar el proyecto**, para poder enseñárselo al usuario antes de aplicarlo.
- `import_master`: lo aplica en **un solo paso de deshacer**.
- `set_master_cells`: varias celdas sueltas de golpe (el pegar de la cuadrícula),
  también en un solo paso de deshacer.

Correspondencia entre columna y campo: vale el nombre técnico (`id`, `name`,
`home_room`...) y la etiqueta en español o en alemán de `columns.LABELS`,
ignorando mayúsculas, acentos, espacios y signos. La lectura del texto la hace
`interop.tabular`, que es genérico; las etiquetas son cosa de esta capa.

Qué se valida (lo mismo que editando celda a celda con `set_master_cell`):
tipo y rango de cada valor, referencias a otras entidades e ids repetidos.

Atomicidad, en dos niveles:

1. **Por fila**: una fila con cualquier error no entra *entera*; no se queda a
   medias con las columnas buenas escritas.
2. **Por importación**: todas las filas buenas se aplican en un único
   `session.apply`, así que un solo Deshacer devuelve el proyecto a como estaba.
   Con `strict=True` basta un error para no aplicar absolutamente nada.

`BulkMixin` es el trozo de Fachada que hereda `UntisService`; toda la lógica
está además en funciones de módulo, para poder usarla sin instanciar la Fachada.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from scheduling_platform.interop.tabular import Table, TableRow, read_table, write_table

from .columns import (
    COLLECTION_OF,
    ENTITY_OF,
    ColumnSpec,
    MasterKind,
    columns,
    format_value,
    parse_value,
)
from .session import UntisSession

#: Cómo se llama cada cuadrícula en los mensajes (singular, plural). La clave es
#: el valor del `MasterKind`; "lessons" es la cuadrícula de Lecciones, que no es
#: un dato maestro pero comparte informe (ver `bulk_lessons`).
KIND_LABELS: dict[str, tuple[str, str]] = {
    MasterKind.CLASSES.value: ("clase", "clases"),
    MasterKind.TEACHERS.value: ("profesor", "profesores"),
    MasterKind.ROOMS.value: ("aula", "aulas"),
    MasterKind.SUBJECTS.value: ("materia", "materias"),
    MasterKind.DEPARTMENTS.value: ("departamento", "departamentos"),
    MasterKind.STUDENT_GROUPS.value: ("grupo de alumnos", "grupos de alumnos"),
    "lessons": ("lección", "lecciones"),
}


def kind_labels(kind: str) -> tuple[str, str]:
    """Nombre en singular y en plural de una cuadrícula, para los mensajes."""
    return KIND_LABELS.get(str(kind), ("fila", "filas"))


#: Cuántos motivos se detallan en el resumen antes de resumir el resto.
ISSUE_PREVIEW = 8

#: Cuántos nombres se listan de cada cosa que falta antes de poner "...".
MISSING_PREVIEW = 5


@dataclass(frozen=True, slots=True)
class MissingHint:
    """Cómo hablarle al usuario de lo que apunta una referencia y no existe."""

    singular: str
    """Con su artículo: `"la rejilla"`, `"el departamento"`."""
    create: str
    """Verbo con el pronombre que toca: `"créala"`, `"créalo"`."""
    plural: str
    where: str
    """Dónde se da de alta, tal y como se llega desde la cinta."""


#: Qué hay que hacer antes, por colección del proyecto a la que apunta la
#: referencia. Un "no existe" a secas deja al usuario sin saber qué tocar.
MISSING_HINTS: dict[str, MissingHint] = {
    "time_grids": MissingHint(
        "la rejilla", "créala", "rejillas de tiempo", "Datos maestros -> Rejillas de tiempo"
    ),
    "departments": MissingHint(
        "el departamento", "créalo", "departamentos", "Datos maestros -> Departamentos"
    ),
    "rooms": MissingHint("el aula", "créala", "aulas", "Datos maestros -> Aulas"),
    "subjects": MissingHint("la materia", "créala", "materias", "Datos maestros -> Materias"),
    "teachers": MissingHint("el profesor", "créalo", "profesores", "Datos maestros -> Profesores"),
    "classes": MissingHint("la clase", "créala", "clases", "Datos maestros -> Clases"),
    "student_groups": MissingHint(
        "el grupo de alumnos",
        "créalo",
        "grupos de alumnos",
        "Datos maestros -> Grupos de alumnos",
    ),
}


def missing_message(reference: str, value: object) -> str:
    """Por qué se rechaza una referencia y qué hacer antes para arreglarlo."""
    pista = MISSING_HINTS.get(reference)
    if pista is None:
        return f"{value!r} no existe"
    return f"{pista.singular} {value!r} no existe: {pista.create} antes en {pista.where}"


def note_missing(missing: dict[str, list[str]], reference: str, value: object) -> None:
    """Apunta lo que falta, sin repetir, para el resumen agrupado del informe."""
    nombres = missing.setdefault(reference, [])
    texto = str(value)
    if texto not in nombres:
        nombres.append(texto)


def missing_pairs(missing: dict[str, list[str]]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Lo que falta como pares `(colección, ids)`, para meterlo en el informe."""
    return tuple((coleccion, tuple(ids)) for coleccion, ids in missing.items() if ids)


#: `dataclasses.replace` sin tipar: las cuadrículas escriben campos por nombre
#: (igual que `UntisService._with_field`) y mypy no puede tipar `**{campo: v}`.
_replace: Callable[..., Any] = dataclasses.replace


class _Entity(Protocol):
    """Lo único que esta capa necesita saber de una entidad de datos maestros."""

    @property
    def id(self) -> str: ...


# --------------------------------------------------------------------------- #
# Resultados
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RowIssue:
    """Un dato rechazado, situado donde el usuario pueda encontrarlo.

    `row` es el número de fila del archivo (1 = la primera de datos; 0 = el
    encabezado), `column` el nombre de columna tal cual venía y `key` el nombre
    corto de la fila si se pudo leer.
    """

    row: int
    column: str
    key: str
    message: str
    field: str = ""
    """Campo del modelo al que corresponde la columna ("" si no se reconoció)."""

    def render(self) -> str:
        sitio = f"fila {self.row}" if self.row else "encabezado"
        if self.key:
            sitio = f"{sitio} ({self.key})"
        if self.column:
            sitio = f"{sitio}, columna «{self.column}»"
        return f"{sitio}: {self.message}"


@dataclass(frozen=True, slots=True)
class ImportReport:
    """Qué entró, qué se actualizó y qué se quedó fuera, con el motivo.

    Lo devuelven igual `preview_import` (con `applied` en falso: nada se tocó) e
    `import_master`, para que la UI enseñe lo mismo antes y después.
    """

    kind: str
    """Valor del `MasterKind` de la cuadrícula, o "lessons"."""
    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    issues: tuple[RowIssue, ...] = ()
    unknown_columns: tuple[str, ...] = ()
    missing: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """Lo que hay que dar de alta antes, agrupado: `(colección, nombres cortos)`.

    Importar las 82 clases de un colegio en un proyecto vacío falla 82 veces por
    lo mismo; esto lo resume en una línea ("faltan 6 rejillas...") para que la
    ventana diga qué hacer en vez de soltar 164 motivos sueltos.
    """
    applied: bool = False
    """`True` solo si la importación llegó a cambiar el proyecto."""

    @property
    def ok(self) -> bool:
        """No hubo ningún dato rechazado."""
        return not self.issues

    @property
    def rows_ok(self) -> int:
        """Filas que entraron (altas + actualizaciones + las que ya estaban igual)."""
        return len(self.created) + len(self.updated) + len(self.unchanged)

    @property
    def rows_failed(self) -> int:
        """Filas de datos que se quedaron fuera."""
        return len({i.row for i in self.issues if i.row})

    def missing_summary(self, limit: int = MISSING_PREVIEW) -> str:
        """Una línea con todo lo que hay que dar de alta antes ("" si no falta nada)."""
        partes: list[str] = []
        for coleccion, nombres in self.missing:
            pista = MISSING_HINTS.get(coleccion)
            como = pista.plural if pista is not None else coleccion
            muestra = ", ".join(nombres[:limit]) + ("..." if len(nombres) > limit else "")
            partes.append(f"{len(nombres)} {como}: {muestra}")
        return f"Faltan {'; '.join(partes)}." if partes else ""

    def summary(self, limit: int = ISSUE_PREVIEW) -> str:
        """Texto para el aviso de la UI: cuántas entraron, cuáles no y por qué."""
        _, plural = kind_labels(self.kind)
        texto = (
            f"{len(self.created)} fila(s) nueva(s), {len(self.updated)} actualizada(s) y "
            f"{len(self.unchanged)} sin cambios en {plural}."
        )
        if not self.issues:
            return texto
        fallidas = self.rows_failed
        if fallidas:
            texto += f" {fallidas} fila(s) no entraron."
        falta = self.missing_summary()
        if falta:
            texto += "\n" + falta
        motivos = [i.render() for i in self.issues[:limit]]
        if len(self.issues) > limit:
            motivos.append(f"...y {len(self.issues) - limit} motivo(s) más")
        return texto + "\n" + "\n".join(motivos)


@dataclass(frozen=True, slots=True)
class CellsResult:
    """Resultado de escribir varias celdas de golpe (el pegar de la cuadrícula)."""

    applied: int
    issues: tuple[RowIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    def summary(self, limit: int = ISSUE_PREVIEW) -> str:
        texto = f"{self.applied} celda(s) pegada(s)."
        if not self.issues:
            return texto
        texto += f" {len(self.issues)} rechazada(s)."
        motivos = [i.render() for i in self.issues[:limit]]
        if len(self.issues) > limit:
            motivos.append(f"...y {len(self.issues) - limit} motivo(s) más")
        return texto + "\n" + "\n".join(motivos)


# --------------------------------------------------------------------------- #
# Correspondencia entre nombre de columna y campo
# --------------------------------------------------------------------------- #


def normalize(name: str) -> str:
    """Clave de comparación de un nombre de columna: sin acentos, signos ni espacios."""
    descompuesto = unicodedata.normalize("NFKD", name.strip().casefold())
    return "".join(c for c in descompuesto if c.isalnum())


def column_map(kind: MasterKind) -> dict[str, ColumnSpec]:
    """Nombre normalizado -> columna. Vale el campo técnico y la etiqueta es/de."""
    cols = columns(kind)
    mapa: dict[str, ColumnSpec] = {normalize(c.field): c for c in cols}
    for c in cols:
        for etiqueta in (c.label, c.label_de):
            mapa.setdefault(normalize(etiqueta), c)
    return mapa


def _entities(session: UntisSession, kind: MasterKind) -> tuple[_Entity, ...]:
    return cast(tuple[_Entity, ...], getattr(session.project, COLLECTION_OF[kind]))


# --------------------------------------------------------------------------- #
# Plan de importación
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Plan:
    """Colección resultante y el informe, todavía sin aplicar."""

    entities: tuple[_Entity, ...]
    report: ImportReport
    changed: bool


def _headers_to_columns(
    kind: MasterKind, headers: tuple[str, ...], issues: list[RowIssue]
) -> tuple[dict[str, ColumnSpec], tuple[str, ...]]:
    """Encabezado -> columna; las que no se reconocen salen como error y se ignoran."""
    mapa = column_map(kind)
    reconocidas: dict[str, ColumnSpec] = {}
    desconocidas: list[str] = []
    for encabezado in headers:
        spec = mapa.get(normalize(encabezado))
        if spec is None:
            desconocidas.append(encabezado)
            issues.append(RowIssue(0, encabezado, "", f"Columna desconocida: {encabezado!r}"))
        else:
            reconocidas[encabezado] = spec
    return reconocidas, tuple(desconocidas)


def _valid_references(
    session: UntisSession, kind: MasterKind, reference: str, file_ids: set[str]
) -> set[str]:
    """Ids válidos de una columna de referencia.

    A los que ya están en el proyecto se suman los del propio archivo cuando la
    referencia apunta a la misma cuadrícula (una cadena de aulas alternativas se
    puede importar de una vez, aunque el aula apuntada esté más abajo).
    """
    existentes = {e.id for e in cast(tuple[_Entity, ...], getattr(session.project, reference, ()))}
    if reference == COLLECTION_OF[kind]:
        existentes |= file_ids
    return existentes


def _row_values(
    fila: TableRow,
    campos: dict[str, ColumnSpec],
    referencias: dict[str, set[str]],
    clave: str,
    issues: list[RowIssue],
    faltan: dict[str, list[str]],
) -> dict[str, object] | None:
    """Valores tipados de una fila, o `None` si algo no pasó la validación."""
    valores: dict[str, object] = {}
    correcta = True
    for encabezado, spec in campos.items():
        if spec.field == "id" or not spec.editable:
            continue
        texto = fila.get(encabezado)
        try:
            valor = parse_value(texto, spec.value_type)
        except ValueError as exc:
            issues.append(RowIssue(fila.number, encabezado, clave, str(exc), spec.field))
            correcta = False
            continue
        desconocida = (
            spec.reference is not None
            and valor not in (None, "")
            and str(valor) not in referencias[spec.reference]
        )
        if desconocida and spec.reference is not None:
            note_missing(faltan, spec.reference, valor)
            issues.append(
                RowIssue(
                    fila.number,
                    encabezado,
                    clave,
                    missing_message(spec.reference, valor),
                    spec.field,
                )
            )
            correcta = False
            continue
        valores[spec.field] = valor
    return valores if correcta else None


def _default_grid(session: UntisSession, kind: MasterKind, valores: dict[str, object]) -> None:
    """Una clase nueva sin rejilla se lleva la primera, como hace `add_master`."""
    rejillas = session.project.time_grids
    if kind is MasterKind.CLASSES and rejillas and not valores.get("time_grid"):
        valores["time_grid"] = rejillas[0].id


def table_from_rows(fields: Sequence[str], block: Sequence[Sequence[str]]) -> Table:
    """Tabla a partir de un bloque ya troceado: el pegar de la cuadrícula.

    Los nombres de columna son los campos del modelo, en el orden en que se ven
    en la cuadrícula; de cada fila se toman tantos valores como columnas haya.
    """
    headers = tuple(fields)
    filas = tuple(
        TableRow(
            numero,
            {h: (celdas[i].strip() if i < len(celdas) else "") for i, h in enumerate(headers)},
        )
        for numero, celdas in enumerate(block, start=1)
    )
    return Table(headers, filas)


def _build_plan(
    session: UntisSession,
    kind: MasterKind,
    source: str | Path | Table,
    *,
    update_existing: bool,
    delimiter: str | None,
) -> _Plan:
    """Calcula la colección resultante y el informe sin tocar la sesión."""
    tabla = source if isinstance(source, Table) else read_table(source, delimiter=delimiter)
    issues = [RowIssue(e.row, e.column, "", e.message) for e in tabla.errors]
    actuales = list(_entities(session, kind))
    vacio = ImportReport(kind, issues=tuple(issues))
    if not tabla.headers:
        return _Plan(tuple(actuales), vacio, False)
    campos, desconocidas = _headers_to_columns(kind, tabla.headers, issues)
    columna_id = next((h for h, s in campos.items() if s.field == "id"), None)
    if columna_id is None:
        etiqueta = columns(kind)[0].label
        issues.append(RowIssue(0, "", "", f"Falta la columna del nombre corto («{etiqueta}»)"))
        return _Plan(tuple(actuales), dataclasses.replace(vacio, issues=tuple(issues)), False)

    ids_archivo = {f.get(columna_id).strip() for f in tabla.rows} - {""}
    referencias = {
        s.reference: _valid_references(session, kind, s.reference, ids_archivo)
        for s in campos.values()
        if s.reference is not None
    }
    posicion = {e.id: i for i, e in enumerate(actuales)}
    faltan: dict[str, list[str]] = {}
    altas: list[_Entity] = []
    cambios: dict[int, _Entity] = {}
    creadas: list[str] = []
    actualizadas: list[str] = []
    iguales: list[str] = []
    vistos: set[str] = set()
    for fila in tabla.rows:
        clave = fila.get(columna_id).strip()
        if not clave:
            issues.append(RowIssue(fila.number, columna_id, "", "El nombre corto está vacío"))
            continue
        if clave in vistos:
            issues.append(
                RowIssue(fila.number, columna_id, clave, f"{clave!r} sale dos veces en el archivo")
            )
            continue
        vistos.add(clave)
        existente = actuales[posicion[clave]] if clave in posicion else None
        if existente is not None and not update_existing:
            issues.append(RowIssue(fila.number, columna_id, clave, f"{clave!r} ya existe"))
            continue
        valores = _row_values(fila, campos, referencias, clave, issues, faltan)
        if valores is None:
            continue
        try:
            if existente is None:
                _default_grid(session, kind, valores)
                nueva = cast(_Entity, ENTITY_OF[kind](id=clave, **valores))
            else:
                nueva = cast(_Entity, _replace(existente, **valores))
        except (ValueError, TypeError) as exc:
            issues.append(RowIssue(fila.number, "", clave, str(exc)))
            continue
        if existente is None:
            altas.append(nueva)
            creadas.append(clave)
        elif nueva == existente:
            iguales.append(clave)
        else:
            cambios[posicion[clave]] = nueva
            actualizadas.append(clave)

    resultantes = list(actuales)
    for indice, entidad in cambios.items():
        resultantes[indice] = entidad
    resultantes.extend(altas)
    informe = ImportReport(
        kind=kind,
        created=tuple(creadas),
        updated=tuple(actualizadas),
        unchanged=tuple(iguales),
        issues=tuple(issues),
        unknown_columns=desconocidas,
        missing=missing_pairs(faltan),
    )
    return _Plan(tuple(resultantes), informe, bool(altas or cambios))


# --------------------------------------------------------------------------- #
# Casos de uso
# --------------------------------------------------------------------------- #


def preview_import(
    session: UntisSession,
    kind: MasterKind,
    source: str | Path | Table,
    *,
    update_existing: bool = True,
    delimiter: str | None = None,
) -> ImportReport:
    """Qué se crearía y qué se actualizaría, y qué está mal. No toca nada."""
    return _build_plan(
        session, kind, source, update_existing=update_existing, delimiter=delimiter
    ).report


def import_master(
    session: UntisSession,
    kind: MasterKind,
    source: str | Path | Table,
    *,
    update_existing: bool = True,
    strict: bool = False,
    delimiter: str | None = None,
) -> ImportReport:
    """Da de alta o actualiza las filas del CSV en un solo paso de deshacer.

    Las filas con errores se quedan fuera enteras y salen en el informe; con
    `strict` un solo error deja el proyecto exactamente como estaba.
    """
    plan = _build_plan(session, kind, source, update_existing=update_existing, delimiter=delimiter)
    if not plan.changed or (strict and plan.report.issues):
        return plan.report
    proyecto = _replace(session.project, **{COLLECTION_OF[kind]: plan.entities})
    singular, plural = kind_labels(kind)
    cuantas = len(plan.report.created) + len(plan.report.updated)
    session.apply(proyecto, f"Importar {cuantas} {plural if cuantas != 1 else singular}")
    return dataclasses.replace(plan.report, applied=True)


def export_master(
    session: UntisSession,
    kind: MasterKind,
    *,
    language: str = "es",
    delimiter: str = ";",
) -> str:
    """CSV de una cuadrícula entera, con la etiqueta de columna en ese idioma.

    Es la vuelta de `import_master`: exportar, editar en Excel y volver a
    importar no pierde ningún campo.
    """
    cols = columns(kind)
    filas = tuple(
        tuple(format_value(getattr(e, c.field), c.value_type) for c in cols)
        for e in _entities(session, kind)
    )
    return write_table(tuple(c.title(language) for c in cols), filas, delimiter=delimiter)


def set_master_cells(
    session: UntisSession,
    kind: MasterKind,
    edits: Sequence[tuple[str, str, str]],
    *,
    label: str = "",
) -> CellsResult:
    """Escribe varias celdas `(nombre corto, campo, texto)` en un solo deshacer.

    Es el pegar de la cuadrícula: valida celda a celda igual que
    `set_master_cell` y las que no pasan se quedan fuera con su motivo, sin
    impedir que entren las demás.
    """
    cols = {c.field: c for c in columns(kind)}
    actuales = list(_entities(session, kind))
    posicion = {e.id: i for i, e in enumerate(actuales)}
    issues: list[RowIssue] = []
    cambiadas: dict[str, _Entity] = {}
    aplicadas = 0
    for clave, campo, texto in edits:
        spec = cols.get(campo)
        if spec is None or not spec.editable:
            issues.append(RowIssue(0, campo, clave, f"La columna {campo!r} no es editable", campo))
            continue
        if clave not in posicion:
            issues.append(RowIssue(0, spec.label, clave, f"No existe {clave!r}", campo))
            continue
        entidad = cambiadas.get(clave, actuales[posicion[clave]])
        try:
            valor = parse_value(texto, spec.value_type)
        except ValueError as exc:
            issues.append(RowIssue(0, spec.label, clave, str(exc), campo))
            continue
        if spec.reference is not None and valor not in (None, ""):
            validos = {
                e.id
                for e in cast(tuple[_Entity, ...], getattr(session.project, spec.reference, ()))
            }
            if str(valor) not in validos:
                issues.append(
                    RowIssue(0, spec.label, clave, missing_message(spec.reference, valor), campo)
                )
                continue
        try:
            cambiadas[clave] = cast(_Entity, _replace(entidad, **{campo: valor}))
        except (ValueError, TypeError) as exc:
            issues.append(RowIssue(0, spec.label, clave, str(exc), campo))
            continue
        aplicadas += 1
    if cambiadas:
        resultantes = list(actuales)
        for clave, entidad in cambiadas.items():
            resultantes[posicion[clave]] = entidad
        proyecto = _replace(session.project, **{COLLECTION_OF[kind]: tuple(resultantes)})
        session.apply(proyecto, label or f"Pegar {aplicadas} celda(s)")
    return CellsResult(aplicadas, tuple(issues))


# --------------------------------------------------------------------------- #
# Trozo de Fachada
# --------------------------------------------------------------------------- #


class BulkMixin:
    """Alta masiva de datos maestros, para heredar en `UntisService`."""

    def preview_import(
        self,
        session: UntisSession,
        kind: MasterKind,
        source: str | Path | Table,
        *,
        update_existing: bool = True,
        delimiter: str | None = None,
    ) -> ImportReport:
        """Qué se crearía y qué se actualizaría, y los errores, sin tocar nada."""
        return preview_import(
            session, kind, source, update_existing=update_existing, delimiter=delimiter
        )

    def import_master(
        self,
        session: UntisSession,
        kind: MasterKind,
        source: str | Path | Table,
        *,
        update_existing: bool = True,
        strict: bool = False,
        delimiter: str | None = None,
    ) -> ImportReport:
        """Aplica el alta o la actualización en un solo paso de deshacer."""
        return import_master(
            session,
            kind,
            source,
            update_existing=update_existing,
            strict=strict,
            delimiter=delimiter,
        )

    def export_master(
        self,
        session: UntisSession,
        kind: MasterKind,
        *,
        language: str = "es",
        delimiter: str = ";",
    ) -> str:
        """CSV de esa cuadrícula, con la etiqueta de columna en el idioma pedido."""
        return export_master(session, kind, language=language, delimiter=delimiter)

    def set_master_cells(
        self,
        session: UntisSession,
        kind: MasterKind,
        edits: Sequence[tuple[str, str, str]],
        *,
        label: str = "",
    ) -> CellsResult:
        """Escribe varias celdas de golpe en un solo paso de deshacer (pegar)."""
        return set_master_cells(session, kind, edits, label=label)
