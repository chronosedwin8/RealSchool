"""Pipeline de calidad del proyecto.

Ejecuta en orden: formato, lint, tipos estrictos y pruebas. Ninguna fase del
plan se cierra sin este script en verde.

Uso:  .venv\\Scripts\\python.exe scripts\\check.py
"""

import subprocess
import sys

PASOS: list[list[str]] = [
    [sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
    [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
    [sys.executable, "-m", "mypy"],
    [sys.executable, "-m", "pytest"],
]


def main() -> int:
    for paso in PASOS:
        legible = " ".join(paso[2:])
        print(f"\n=== {legible} ===", flush=True)
        codigo = subprocess.run(paso).returncode
        if codigo != 0:
            print(f"\nFALLÓ: {legible}", flush=True)
            return codigo
    print("\nPipeline de calidad: TODO EN VERDE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
