"""Fronteras entre capas de la refactorización Untis (R0, ver ADR-034).

Arquitectura objetivo (`REFACTOR_UNTIS_MAESTRO.md`, sección 4)::

    untis_desktop -> application -> untis_model
                                 -> interop  -> untis_model
                                 -> bridge   -> motor congelado + heuristic
    heuristic -> untis_model   (algoritmo puro, sin motor)

Reglas:

1. `untis_model` es dominio puro: no importa nada de `scheduling_platform`.
2. `interop` solo importa `untis_model` (salvo el convertidor legado `.bjs`).
3. `heuristic` solo importa `untis_model`: el pulido CP-SAT lo orquesta `bridge`.
4. Fuera del motor congelado, **solo `bridge`** importa el motor. Las capas
   legadas que aún lo hacen están en `LEGACY_ENGINE_IMPORTERS`; esa lista solo
   puede encoger a medida que las fases las retiran.
5. El motor congelado nunca importa capas de producto.
6. `untis_desktop` solo importa la Fachada (`scheduling_platform.application`).

El análisis es por AST (no por texto): resuelve imports relativos y no se deja
engañar por menciones en docstrings o comentarios.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
PLATFORM = SRC / "scheduling_platform"
DESKTOP = SRC / "untis_desktop"

#: Motor congelado en `engine-1.0`. Solo cambia por extensiones con ADR propio.
FROZEN_ENGINE = frozenset(
    {"core", "dsl", "cir", "sal", "pipeline", "engine", "plugins", "benchmarks"}
)

#: Capas de producto nuevas (R1+).
PRODUCT_LAYERS = frozenset({"untis_model", "interop", "bridge", "heuristic"})

#: Capas legadas que todavía importan el motor directamente. Cada fase que
#: retire una de ellas debe quitarla de aquí (la prueba falla si sobra alguna).
LEGACY_ENGINE_IMPORTERS = frozenset({"academic", "application", "serialization", "untis"})

#: Único módulo de `interop` autorizado a leer estructuras legadas.
INTEROP_LEGACY_MODULE = "bjs_legacy"


@dataclass(frozen=True, slots=True)
class Edge:
    """Un import de `archivo` hacia la capa `target` de scheduling_platform."""

    source: Path
    layer: str
    target: str

    def __str__(self) -> str:
        return f"{self.source.relative_to(SRC)} -> {self.target}"


def _layer_of(path: Path) -> str:
    partes = path.relative_to(PLATFORM).parts
    return partes[0] if len(partes) > 1 else "(raíz)"


def _targets(path: Path) -> set[str]:
    """Capas de `scheduling_platform` que importa un archivo."""
    arbol = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    paquete = path.relative_to(SRC).with_suffix("").parts[:-1]
    capas: set[str] = set()
    for nodo in ast.walk(arbol):
        modulos: list[tuple[str, ...]] = []
        if isinstance(nodo, ast.Import):
            modulos = [tuple(a.name.split(".")) for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            base = tuple(nodo.module.split(".")) if nodo.module else ()
            if nodo.level:
                subir = nodo.level - 1
                ancla = paquete[: len(paquete) - subir] if subir else paquete
                modulos = [ancla + base]
            else:
                modulos = [base]
        for mod in modulos:
            if len(mod) >= 2 and mod[0] == "scheduling_platform":
                capas.add(mod[1])
    return capas


@cache
def _platform_edges() -> tuple[Edge, ...]:
    aristas: list[Edge] = []
    for f in sorted(PLATFORM.rglob("*.py")):
        capa = _layer_of(f)
        for destino in sorted(_targets(f)):
            if destino != capa:
                aristas.append(Edge(f, capa, destino))
    return tuple(aristas)


def _violations(layer: str, allowed: frozenset[str]) -> list[str]:
    return [str(e) for e in _platform_edges() if e.layer == layer and e.target not in allowed]


# --------------------------------------------------------------------------- #
# Reglas
# --------------------------------------------------------------------------- #


def test_untis_model_es_dominio_puro() -> None:
    assert _violations("untis_model", frozenset()) == []


def test_interop_solo_conoce_el_modelo() -> None:
    malos = [
        str(e)
        for e in _platform_edges()
        if e.layer == "interop"
        and e.target != "untis_model"
        and e.source.stem != INTEROP_LEGACY_MODULE
    ]
    assert malos == [], f"interop solo puede importar untis_model: {malos}"


def test_heuristic_no_toca_el_motor() -> None:
    assert _violations("heuristic", frozenset({"untis_model"})) == []


def test_solo_bridge_importa_el_motor() -> None:
    autorizados = {"bridge", *FROZEN_ENGINE, *LEGACY_ENGINE_IMPORTERS}
    malos = [
        str(e)
        for e in _platform_edges()
        if e.target in FROZEN_ENGINE
        and e.layer not in autorizados
        and not (e.layer == "interop" and e.source.stem == INTEROP_LEGACY_MODULE)
    ]
    assert malos == [], f"Fuera de bridge nadie importa el motor: {malos}"


def test_la_lista_legada_solo_encoge() -> None:
    """Si una capa legada ya no importa el motor, hay que quitarla de la lista."""
    importan = {e.layer for e in _platform_edges() if e.target in FROZEN_ENGINE}
    sobrantes = sorted(LEGACY_ENGINE_IMPORTERS - importan)
    assert sobrantes == [], f"Quita de LEGACY_ENGINE_IMPORTERS: {sobrantes}"


def test_el_motor_no_importa_el_producto() -> None:
    producto = {*PRODUCT_LAYERS, "application", "cli"}
    malos = [str(e) for e in _platform_edges() if e.layer in FROZEN_ENGINE and e.target in producto]
    assert malos == [], f"El motor congelado no depende del producto: {malos}"


@pytest.mark.skipif(not DESKTOP.is_dir(), reason="untis_desktop aún no existe (R4)")
def test_untis_desktop_solo_importa_la_fachada() -> None:
    malos: list[str] = []
    for f in sorted(DESKTOP.rglob("*.py")):
        for capa in sorted(_targets(f)):
            if capa != "application":
                malos.append(f"{f.relative_to(SRC)} -> {capa}")
    assert malos == [], f"untis_desktop solo puede importar la Fachada: {malos}"


def test_el_escaner_resuelve_imports_relativos() -> None:
    """Autoprueba: `from ..core import X` cuenta como import de `core`.

    Sin esto, una capa podría saltarse las reglas con imports relativos.
    """
    relativo = PLATFORM / "engine" / "engine.py"  # motor congelado: `from ..core import ...`
    assert "core" in _targets(relativo)
    # `from .x import Y` resuelve a la propia capa, que las reglas ignoran.
    interno = PLATFORM / "core" / "problem.py"
    assert _targets(interno) == {"core"}
    assert _layer_of(interno) == "core"


def test_academic_esta_obsoleto() -> None:
    """R0: `academic` avisa de su retirada (ADR-034)."""
    import importlib

    import scheduling_platform.academic as academic

    with pytest.warns(DeprecationWarning, match="untis_model"):
        importlib.reload(academic)
