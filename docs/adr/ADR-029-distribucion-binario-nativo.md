# ADR-029: Distribución como binario nativo (H11), validada en contenedor limpio

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
La Fase 2 (H11) pedía un ejecutable nativo que corra sin Python instalado. Quedó
diferido porque no se podía validar el criterio de éxito ("corre en una VM
limpia") sin un entorno limpio. La Fase 3 lo cierra usando **Docker** como ese
entorno limpio.

## Decisión

### 1. Herramienta: PyInstaller (Nuitka evaluado)
Nuitka fue la primera recomendación (H11), pero para **OR-Tools** —que arrastra
librerías nativas C++ (CP-SAT) y protobuf— **PyInstaller** es la elección
pragmática: `--onefile --collect-all ortools` empaqueta esas dependencias sin
fricción y compila en minutos. Es exactamente el *fallback* que el plan de Fase 2
anticipó; el criterio de éxito es "binario que corre en entorno limpio", no la
herramienta. `packaging/entry.py` es el punto de entrada (los empaquetadores
necesitan un script, no `module:attr`).

### 2. Validación real en runtime limpio (Docker multi-stage)
El `Dockerfile` compila en `python:3.14-slim` y copia **solo el binario** a una
imagen `debian:bookworm-slim` **sin Python** (única lib de sistema extra:
`libgomp1`, el OpenMP que usa CP-SAT). En esa imagen limpia se verificó:
- `doctor` → detecta los 4 solvers (CP-SAT/CBC/SCIP/HiGHS).
- `convert /data/untis.xml` → importa los datos reales (1822 clases, 265 recursos).
- `project info` → relee el `.bjs`.
- `generate --json-stream` → construye el modelo (20 070 variables), emite el
  stream de progreso y respeta el timeout (exit 3) — todo el pipeline de solver
  funciona en el binario congelado.

### 3. Matriz de compilación (CI)
`.github/workflows/build.yml` compila con PyInstaller en Linux/Windows/macOS,
hace un smoke test (`doctor`) y publica cada binario como artifact.

## Consecuencias
- **Positivas:** H11 cerrado con evidencia real — un binario nativo autónomo que
  corre sin Python, verificado sobre datos reales en un contenedor limpio. La
  distribución no exige que el cliente instale Python, dependencias ni variables.
- **Límites conocidos:** dentro del binario congelado, `importlib.metadata` no
  encuentra la metadata de algunos paquetes (psutil/pyyaml → "n/a" en `doctor`) y
  `git` no está disponible (git_commit → "unknown" en la firma del `.bjs`). Son
  cosméticos: la funcionalidad (solvers, parsing, solving, streams) es completa.
- El binario Linux se valida en el propio Docker; Windows/macOS vía la matriz de
  Actions (runners nativos).
