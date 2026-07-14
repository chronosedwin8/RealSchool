"""Ejecuta un benchmark sobre un dataset sintético.

Uso:
    .venv\\Scripts\\python.exe scripts\\benchmark.py [small|medium|large|xl] [segundos]

Imprime la evidencia (latencia por etapa, tamaño del modelo, RAM, calidad) y la
vuelca en JSON para poder comparar entre versiones.
"""

from __future__ import annotations

import json
import sys

from scheduling_platform.benchmarks import PRESETS, BenchmarkRunner
from scheduling_platform.sal.interface import SolverConfig
from scheduling_platform.sal.ortools_solver import ORToolsSolver


def main() -> int:
    preset = sys.argv[1] if len(sys.argv) > 1 else "small"
    limite = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0

    if preset not in PRESETS:
        print(f"preset desconocido: {preset}. Opciones: {', '.join(PRESETS)}")
        return 1

    spec = PRESETS[preset]
    print(f"Ejecutando '{spec.name}' con límite de {limite:.0f}s...\n", flush=True)

    runner = BenchmarkRunner(solver_factory=ORToolsSolver)
    run = runner.run(
        spec,
        SolverConfig(max_time_in_seconds=limite, num_search_workers=8, random_seed=1),
    )

    print(run.render())
    print("\nJSON:")
    print(json.dumps(run.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
