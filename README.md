# RealSchool — Scheduling Optimization Platform

Creador de horarios de colegios: motor genérico de calendarización por
restricciones (primer módulo, el académico), construido sobre Google OR-Tools
CP-SAT detrás de una Solver Abstraction Layer.

- **Especificación (fuente de verdad):** [Prompt3.md](Prompt3.md)
- **Plan de fases y estrategia de pruebas:** [PLAN_DE_TRABAJO.md](PLAN_DE_TRABAJO.md)
- **Decisiones de arquitectura:** [docs/adr/](docs/adr/)

## Arquitectura de capas (dependencias solo hacia abajo)

```
academic  →  core (Modelo Canónico)  →  dsl  →  cir  →  sal (única capa que conoce ortools)
                                 pipeline (orquesta)      plugins (declaran reglas vía dsl)
```

El dominio no conoce el solver: en todo el repositorio existe una sola línea
`import ortools`, dentro de `sal/ortools_solver.py`, y hay pruebas automáticas
que lo verifican.

## Pipeline de compilación

```
academic → adapter → problema canónico → plugins (DSL)
    → Constraint Graph Builder (infactibilidad + explicación)
    → lower → CIR → Optimizer Passes → Solver Compiler → ISolver → horario
```

## Entorno de desarrollo

Requiere el Python del sistema (3.14.3). No instalar otras versiones.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Verificación de calidad (obligatoria antes de cerrar cualquier fase)

```powershell
.\.venv\Scripts\python.exe scripts\check.py
```

Ejecuta en orden: `ruff format --check`, `ruff check`, `mypy --strict` y `pytest`.
