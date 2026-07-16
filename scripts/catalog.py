"""Imprime el catálogo canónico de restricciones (Actividad 2, documentación viva).

Uso:
    .venv\\Scripts\\python.exe scripts\\catalog.py
"""

from __future__ import annotations

import sys

from scheduling_platform.plugins import CONSTRAINT_CATALOG, render_catalog_table


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # el catálogo usa '∞'
    print(render_catalog_table())
    print()
    hard = sum(1 for d in CONSTRAINT_CATALOG if d.kind.value == "hard")
    soft = sum(1 for d in CONSTRAINT_CATALOG if d.kind.value == "soft")
    print(f"Total: {len(CONSTRAINT_CATALOG)} restricciones ({hard} duras, {soft} blandas).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
