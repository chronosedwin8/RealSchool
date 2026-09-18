"""Inventario de campos de un export XmlInterface de Untis y su cobertura en el modelo.

Recorre uno o más XML de Untis y lista cada ruta de elemento o atributo que
lleva datos (texto o atributo no vacíos), con cuántos valores aparecen. Cada
ruta se clasifica con las constantes de `scheduling_platform.interop.xml`:

- REGENERATED: metadato derivado que se reconstruye al escribir
  (`REGENERATED_FIELDS`).
- DROPPED: dato que se pierde; o bien está en `DROPPED_FIELDS`, o bien se dice
  modelado pero la ida y vuelta no lo conserva.
- MODELED: el resto, **verificado**: tras `read_xml` -> `write_xml` la misma
  ruta lleva exactamente el mismo multiconjunto de valores (con los ids
  normalizados sin prefijo de tipo, porque un id sin prefijo lo recibe al
  escribirse).

Sale con código 1 si alguna ruta con datos queda DROPPED.

    python scripts/xml_fields_inventory.py                 # fixtures por defecto
    python scripts/xml_fields_inventory.py export.xml ...  # exports concretos
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from scheduling_platform.interop.xml import (
    DROPPED_FIELDS,
    ID_PREFIXES,
    REGENERATED_FIELDS,
    read_xml,
    write_xml,
)

_ROOT: Final = Path(__file__).resolve().parent.parent
_FIXTURES: Final = _ROOT / "tests" / "fixtures"
_XSI: Final = "{http://www.w3.org/2001/XMLSchema-instance}"
#: Un prefijo de tipo al principio de un id o tras el espacio que separa dos ids.
_PREFIX_RE: Final = re.compile(r"(^|\s)(?:" + "|".join(re.escape(p) for p in ID_PREFIXES) + ")")


class Coverage(StrEnum):
    """Destino de una ruta del XML en el modelo."""

    MODELED = "MODELED"
    REGENERATED = "REGENERATED"
    DROPPED = "DROPPED"


@dataclass(frozen=True, slots=True)
class FieldReport:
    """Una ruta con datos: cuántos valores lleva y qué le pasa en el modelo."""

    path: str
    count: int
    coverage: Coverage
    note: str = ""


type Values = dict[str, Counter[str]]
"""Valores por ruta (`document/classes/class/@id` -> multiconjunto)."""


def default_files() -> list[Path]:
    """Exports reales locales (si hay) más el seudonimizado versionado."""
    reales = sorted((_FIXTURES / "real").glob("*.xml"))
    anon = _FIXTURES / "untis_anon.xml"
    return [*reales, *([anon] if anon.is_file() else [])]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr_name(name: str) -> str:
    if name.startswith(_XSI):
        return f"xsi:{name[len(_XSI) :]}"
    return _local(name)


def _normalize(attr: str, value: str) -> str:
    """Los ids se comparan sin prefijo de tipo (`CL_K1A` y `K1A` son el mismo)."""
    return _PREFIX_RE.sub(r"\1", value) if attr == "id" else value


def collect_values(root: ET.Element) -> Values:
    """Rutas con datos de un documento y sus valores."""
    valores: Values = {}

    def visitar(element: ET.Element, padre: str) -> None:
        ruta = f"{padre}/{_local(element.tag)}" if padre else _local(element.tag)
        texto = (element.text or "").strip()
        if texto:
            valores.setdefault(ruta, Counter())[texto] += 1
        for nombre, valor in element.attrib.items():
            if valor.strip():
                attr = _attr_name(nombre)
                clave = f"{ruta}/@{attr}"
                valores.setdefault(clave, Counter())[_normalize(attr, valor.strip())] += 1
        for hijo in element:
            visitar(hijo, ruta)

    visitar(root, "")
    return valores


def _declared_in(path: str, entries: Iterable[str]) -> bool:
    """`True` si alguna entrada (`time/assigned_starttime`, `holidays`) cubre la ruta."""
    envuelta = f"/{path}/"
    return any(f"/{e}/" in envuelta for e in entries)


def inventory_file(path: Path, workdir: Path) -> list[FieldReport]:
    """Clasifica las rutas con datos de un XML comparándolo con su reescritura."""
    original = collect_values(ET.parse(path).getroot())
    reescrito_path = workdir / f"{path.stem}.rewritten.xml"
    write_xml(read_xml(path), reescrito_path)
    reescrito = collect_values(ET.parse(reescrito_path).getroot())

    informe: list[FieldReport] = []
    for ruta, valores in sorted(original.items()):
        total = sum(valores.values())
        if _declared_in(ruta, REGENERATED_FIELDS):
            informe.append(FieldReport(ruta, total, Coverage.REGENERATED))
        elif _declared_in(ruta, DROPPED_FIELDS):
            informe.append(FieldReport(ruta, total, Coverage.DROPPED, "sin sitio en el modelo"))
        elif reescrito.get(ruta, Counter()) == valores:
            informe.append(FieldReport(ruta, total, Coverage.MODELED))
        else:
            faltan = sum((valores - reescrito.get(ruta, Counter())).values())
            informe.append(
                FieldReport(
                    ruta, total, Coverage.DROPPED, f"la ida y vuelta pierde {faltan} valores"
                )
            )
    return informe


def inventory(paths: Sequence[Path]) -> list[FieldReport]:
    """Inventario conjunto: suma los valores por ruta y se queda con el peor destino."""
    orden = (Coverage.MODELED, Coverage.REGENERATED, Coverage.DROPPED)
    conjunto: dict[str, FieldReport] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for i, path in enumerate(paths):
            carpeta = Path(tmp) / str(i)
            carpeta.mkdir()
            for fila in inventory_file(path, carpeta):
                previa = conjunto.get(fila.path)
                if previa is None:
                    conjunto[fila.path] = fila
                    continue
                peor = max(previa, fila, key=lambda f: orden.index(f.coverage))
                conjunto[fila.path] = FieldReport(
                    fila.path, previa.count + fila.count, peor.coverage, peor.note
                )
    return [conjunto[r] for r in sorted(conjunto)]


def dropped_with_data(report: Iterable[FieldReport]) -> list[FieldReport]:
    """Rutas con datos que el modelo pierde (debe quedar vacía)."""
    return [f for f in report if f.coverage is Coverage.DROPPED]


def render(report: Sequence[FieldReport]) -> str:
    """Tabla de cobertura en texto plano."""
    ancho = max((len(f.path) for f in report), default=4)
    lineas = [f"{'Ruta':<{ancho}}  {'Valores':>7}  Estado", "-" * (ancho + 30)]
    lineas += [
        f"{f.path:<{ancho}}  {f.count:>7}  {f.coverage.value}" + (f"  ({f.note})" if f.note else "")
        for f in report
    ]
    cuentas = Counter(f.coverage for f in report)
    conservadas = cuentas[Coverage.MODELED] + cuentas[Coverage.REGENERATED]
    porcentaje = 100.0 * conservadas / len(report) if report else 100.0
    lineas += [
        "",
        f"Rutas con datos: {len(report)}  MODELED: {cuentas[Coverage.MODELED]}  "
        f"REGENERATED: {cuentas[Coverage.REGENERATED]}  DROPPED: {cuentas[Coverage.DROPPED]}",
        f"Cobertura: {conservadas}/{len(report)} ({porcentaje:.1f} %)",
        f"Secciones sin sitio en el modelo (vacías si no figuran arriba): "
        f"{', '.join(DROPPED_FIELDS)}",
    ]
    return "\n".join(lineas)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("xml", nargs="*", type=Path, help="exports XmlInterface de Untis")
    args = parser.parse_args(argv)
    archivos: list[Path] = list(args.xml) or default_files()
    if not archivos:
        print("No hay XML que inventariar.", file=sys.stderr)
        return 2
    print("Archivos:")
    for a in archivos:
        print(f"  {a}")
    print()
    informe = inventory(archivos)
    print(render(informe))
    return 1 if dropped_with_data(informe) else 0


if __name__ == "__main__":
    sys.exit(main())
