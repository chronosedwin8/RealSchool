"""La wiki de usuario (`docs/wiki/`) está completa y no tiene enlaces rotos.

Una wiki que envejece mal es peor que no tenerla: estas pruebas fallan si se
añade una ventana sin su página, si un enlace o una imagen no existen, o si
alguien mete en una captura un dato personal del colegio real.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from untis_desktop.registry import load_windows

WIKI = Path(__file__).resolve().parents[1] / "docs" / "wiki"
IMG = WIKI / "img"

#: Enlaces `[texto](destino)` y `![texto](destino)` de una página.
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")

#: Páginas que tiene que haber, además de `Home.md`.
PAGES: tuple[str, ...] = (
    "01-primeros-pasos.md",
    "02-datos-maestros.md",
    "03-rejillas-de-tiempo.md",
    "04-deseos-y-marco-horario.md",
    "05-lecciones.md",
    "06-ponderacion.md",
    "07-generar-el-horario.md",
    "08-diagnostico-y-evaluacion.md",
    "09-planificacion-manual.md",
    "10-horarios-impresion-y-pdf.md",
    "11-guardias-de-recreo.md",
    "12-sustituciones.md",
    "13-importar-y-exportar.md",
    "14-atajos-y-trucos.md",
    "15-preguntas-frecuentes.md",
)


def paginas() -> list[Path]:
    return sorted(WIKI.glob("*.md"))


def test_estan_todas_las_paginas() -> None:
    faltan = [n for n in ("Home.md", *PAGES) if not (WIKI / n).is_file()]
    assert not faltan, f"faltan páginas de la wiki: {faltan}"


def test_el_indice_enlaza_todas_las_paginas() -> None:
    home = (WIKI / "Home.md").read_text(encoding="utf-8")
    faltan = [n for n in PAGES if n not in home]
    assert not faltan, f"el índice no enlaza: {faltan}"


@pytest.mark.parametrize("pagina", paginas(), ids=lambda p: p.name)
def test_los_enlaces_y_las_imagenes_existen(pagina: Path) -> None:
    texto = pagina.read_text(encoding="utf-8")
    rotos: list[str] = []
    for destino in LINK.findall(texto):
        limpio = destino.split("#")[0].strip()
        if not limpio or limpio.startswith(("http://", "https://", "mailto:")):
            continue
        if not (pagina.parent / limpio).exists():
            rotos.append(destino)
    assert not rotos, f"{pagina.name}: enlaces rotos {rotos}"


@pytest.mark.parametrize("pagina", paginas(), ids=lambda p: p.name)
def test_cada_pagina_tiene_titulo_y_contenido(pagina: Path) -> None:
    lineas = pagina.read_text(encoding="utf-8").splitlines()
    assert lineas and lineas[0].startswith("# "), f"{pagina.name} sin título"
    assert len(lineas) > 20, f"{pagina.name} demasiado corta"


def test_cada_ventana_de_la_aplicacion_sale_en_la_wiki() -> None:
    """Una ventana nueva sin documentar rompe aquí."""
    todo = "\n".join(p.read_text(encoding="utf-8") for p in paginas())
    faltan = [s.key for s in load_windows() if s.title.lower() not in todo.lower()]
    assert not faltan, f"ventanas sin documentar en la wiki: {faltan}"


def test_las_capturas_se_usan_y_no_estan_vacias() -> None:
    todo = "\n".join(p.read_text(encoding="utf-8") for p in paginas())
    imagenes = sorted(IMG.glob("*.png"))
    assert imagenes, "no hay capturas en docs/wiki/img"
    sueltas = [i.name for i in imagenes if i.name not in todo]
    assert not sueltas, f"capturas que no usa ninguna página: {sueltas}"
    vacias = [i.name for i in imagenes if i.stat().st_size < 5_000]
    assert not vacias, f"capturas sospechosamente pequeñas: {vacias}"


def test_las_capturas_no_llevan_datos_del_colegio_real() -> None:
    """Las capturas salen del ejemplo seudonimizado, nunca del export real."""
    real = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real"
    assert not any(p.name.startswith("real") for p in IMG.glob("*")), "capturas del export real"
    guion = (Path(__file__).resolve().parents[1] / "scripts" / "wiki_shots.py").read_text(
        encoding="utf-8"
    )
    assert "untis_anon.xml" in guion
    assert real.name not in guion
