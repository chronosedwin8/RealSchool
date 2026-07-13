# ADR-001: Python 3.14.3 del sistema + venv/pip como toolchain

**Fecha:** 2026-07-13 · **Estado:** Aceptado

## Contexto
La especificación exige Python 3.13+ con typing estricto. El equipo dispone de
Python 3.14.3 instalado (`C:\Python314`) y pidió explícitamente no instalar
otras versiones del intérprete.

## Alternativas evaluadas
1. **uv** — más rápido y con lockfile, pero su gestión de intérpretes tiende a
   descargar versiones propias de Python, lo que contradice la restricción.
2. **poetry** — lockfile maduro, pero añade una herramienta externa más.
3. **venv + pip estándar** — sin instalaciones adicionales, usa el intérprete
   del sistema tal cual; menos features (sin lockfile).

## Decisión adoptada
Opción 3: `python -m venv .venv` + `pip`, con dependencias declaradas en
`pyproject.toml` (PEP 621) y extras `[dev]`. Python 3.14.3 supera el mínimo
3.13+ de la especificación y OR-Tools 9.15 publica wheel nativo cp314.

## Consecuencias técnicas
Cero instalaciones de intérpretes; entorno reproducible vía `pyproject.toml`
(sin lockfile exacto — si más adelante se necesita, puede añadirse
`pip freeze > requirements-lock.txt` o migrar a uv sin tocar el código).
El venv vive dentro de una carpeta sincronizada por OneDrive; si la
sincronización degrada el rendimiento, se recomienda excluir `.venv/` de
OneDrive o mover el proyecto fuera de la carpeta sincronizada.
