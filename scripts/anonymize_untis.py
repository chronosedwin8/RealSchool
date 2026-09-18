"""Seudonimiza un export XmlInterface de Untis para poder versionarlo.

Uso:
    .venv\\Scripts\\python.exe scripts\\anonymize_untis.py ENTRADA.xml SALIDA.xml

Los exports reales contienen nombres, correos y números de nómina (que en
Colombia suelen ser la cédula). Este script conserva **toda** la estructura que
importa para la regresión —rejillas, lecciones, acoples, bloques, horas y
colocaciones— y reemplaza de forma determinista todo dato personal:

- ids de profesor (codifican el apellido y la inicial) → `TR_T001`…, reescritos
  también en cada `lesson_teacher` que los referencia;
- nombre, apellido, correo, nómina, género y texto libre de profesores;
- `longname`/`text` de clases y aulas (el colegio los usa para correos y nombres);
- la cabecera del colegio.

Es determinista: el mismo export produce siempre el mismo fichero.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

URI = "https://untis.at/untis/XmlInterface"
NS = f"{{{URI}}}"

#: Campos de profesor que se vacían o reemplazan por completo.
_TEACHER_PERSONAL = ("surname", "forename", "email", "payrollnumber", "gender", "text", "status")


def _tag(el: ET.Element) -> str:
    return el.tag.removeprefix(NS)


def _set_text(parent: ET.Element, child: str, value: str) -> None:
    el = parent.find(f"{NS}{child}")
    if el is not None:
        el.text = value


def anonymize(tree: ET.ElementTree[ET.Element]) -> ET.ElementTree[ET.Element]:
    """Seudonimiza el árbol en sitio y lo devuelve."""
    root = tree.getroot()

    general = root.find(f"{NS}general")
    if general is not None:
        _set_text(general, "header1", "Colegio de Ejemplo")
        _set_text(general, "schoolname", "Untis")

    # --- profesores: nuevo id + datos personales fuera -------------------- #
    teachers = root.find(f"{NS}teachers")
    remap: dict[str, str] = {}
    if teachers is not None:
        for n, t in enumerate(teachers, start=1):
            old = t.get("id", "")
            new = f"TR_T{n:03d}"
            remap[old] = new
            t.set("id", new)
            for campo in _TEACHER_PERSONAL:
                el = t.find(f"{NS}{campo}")
                if el is None:
                    continue
                if campo == "surname":
                    el.text = f"Apellido{n:03d}"
                elif campo == "forename":
                    el.text = f"Nombre{n:03d}"
                elif campo == "email":
                    el.text = f"t{n:03d}@example.org"
                else:
                    el.text = ""

    for el in root.iter(f"{NS}lesson_teacher"):
        old = el.get("id", "")
        if old in remap:
            el.set("id", remap[old])

    # --- clases y aulas: longname/text con correos y nombres -------------- #
    for coleccion, prefijo in (("classes", "Clase"), ("rooms", "Aula")):
        nodo = root.find(f"{NS}{coleccion}")
        if nodo is None:
            continue
        for n, ent in enumerate(nodo, start=1):
            _set_text(ent, "longname", f"{prefijo} {n:03d}")
            _set_text(ent, "text", "")

    return tree


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    ET.register_namespace("", URI)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    tree = anonymize(ET.parse(src))
    ET.indent(tree, space="  ")
    tree.write(dst, encoding="utf-8", xml_declaration=True)
    print(f"Seudonimizado: {src.name} -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
