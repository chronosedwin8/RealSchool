"""Traducciones de la UI de escritorio (decisión 3 del documento maestro).

El español es el idioma fuente (los textos van en `self.tr("...")`). Este
script:

1. ejecuta `pyside6-lupdate` sobre `src/untis_desktop` para crear o actualizar
   `src/untis_desktop/translations/untis_desktop_de.ts` (conserva las
   traducciones ya hechas y marca como pendientes las cadenas nuevas);
2. ejecuta `pyside6-lrelease` para compilar `untis_desktop_de.qm`, que es lo que
   carga la aplicación (`untis_desktop.i18n.install_translator`).

Uso:  .venv\\Scripts\\python.exe scripts\\i18n.py [--release-only]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "src" / "untis_desktop"
TRANSLATIONS = SOURCES / "translations"
LANGUAGES: tuple[str, ...] = ("de",)


def tool(name: str) -> str:
    """Ruta de una herramienta de PySide6 (junto al intérprete o en el PATH)."""
    carpeta = Path(sys.executable).parent
    for candidato in (carpeta / f"{name}.exe", carpeta / name):
        if candidato.is_file():
            return str(candidato)
    encontrado = shutil.which(name)
    if encontrado is None:
        raise FileNotFoundError(f"No se encuentra {name}: ¿está instalado PySide6?")
    return encontrado


def sources() -> list[Path]:
    """Módulos Python de la UI (excluye cachés)."""
    return sorted(p for p in SOURCES.rglob("*.py") if "__pycache__" not in p.parts)


def ts_path(language: str) -> Path:
    return TRANSLATIONS / f"untis_desktop_{language}.ts"


def qm_path(language: str) -> Path:
    return TRANSLATIONS / f"untis_desktop_{language}.qm"


def run(command: list[str]) -> int:
    print(" ".join(Path(c).name if i == 0 else c for i, c in enumerate(command)), flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def update(language: str) -> int:
    """Extrae las cadenas de las fuentes al `.ts` del idioma."""
    TRANSLATIONS.mkdir(parents=True, exist_ok=True)
    archivos = [str(p.relative_to(ROOT)) for p in sources()]
    return run(
        [
            tool("pyside6-lupdate"),
            *archivos,
            "-source-language",
            "es",
            "-target-language",
            language,
            "-ts",
            str(ts_path(language).relative_to(ROOT)),
        ]
    )


def release(language: str) -> int:
    """Compila el `.ts` a `.qm`."""
    return run(
        [
            tool("pyside6-lrelease"),
            str(ts_path(language).relative_to(ROOT)),
            "-qm",
            str(qm_path(language).relative_to(ROOT)),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--release-only",
        action="store_true",
        help="solo compila los .ts existentes (no vuelve a extraer cadenas)",
    )
    args = parser.parse_args(argv)
    for idioma in LANGUAGES:
        if not args.release_only:
            codigo = update(idioma)
            if codigo != 0:
                return codigo
        codigo = release(idioma)
        if codigo != 0:
            return codigo
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
