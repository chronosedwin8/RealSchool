# RealSchool

Creador de horarios escolares con el modelo de trabajo de Untis —datos maestros,
lecciones con acoples, deseos −3…+3, ponderación 0–5, estrategias A/B/D/E,
Diagnóstico y Diálogo de planificación— sobre un motor propio que Untis no
tiene: CP-SAT exacto para reparar con cambio mínimo, pulir y demostrar
infactibilidad.

- **Fuente de verdad:** [REFACTOR_UNTIS_MAESTRO.md](REFACTOR_UNTIS_MAESTRO.md)
  (supersede a `Prompt3.md` y `PLAN_DE_TRABAJO.md` en lo que contradiga; ver
  [ADR-034](docs/adr/ADR-034-reorientacion-a-untis.md)).
- **Decisiones de arquitectura:** [docs/adr/](docs/adr/)
- **Estado de la refactorización:** [PLAN_DE_TRABAJO.md](PLAN_DE_TRABAJO.md#refactorización-untis-r0r5)

## Arquitectura

```
untis_desktop ──> application (Fachada, proyecto .rsp)
                     ├──> untis_model   dominio Untis puro + evaluador de referencia
                     ├──> interop       XmlInterface · GPU · .rsp   ──> untis_model
                     └──> bridge        único traductor al motor    ──> motor congelado
                                         └──> heuristic  colocación + intercambios ──> untis_model
motor congelado (engine-1.0): core · dsl · cir · sal · pipeline · engine · plugins · benchmarks
```

Las fronteras se verifican por AST en `tests/test_boundaries.py`: `untis_model`
no importa nada; `interop` y `heuristic` solo el modelo; fuera del motor, solo
`bridge` lo importa; la UI solo la Fachada.

## Lo que ya funciona (datos reales, curso 2025-2026)

| Qué | Resultado |
| --- | --- |
| Importar el XML de Untis | 66 clases, 116 profesores, 709 lecciones, 8 rejillas; ida y vuelta idéntica; 100 % de los campos con datos modelados |
| Exportar GPU001 | `4,"K1A","T028","MATK1","P 11",1,7,,` — nombres cortos, listo para MiUntisWeb |
| Fidelidad del puente | evaluador, `ValidationEngine` y barrido del reloj ven los mismos 7 choques reales del horario publicado, ni uno más |
| Reparar (CP-SAT) | 7 choques → 0 en 0,6 s moviendo 6 de 1.676 sesiones |
| Pulir (CP-SAT por ventanas) | −28 % de puntos blandos en 60 s, sin choques |
| Generar desde cero (heurística) | A: 60 s, B: 300 s; 0 sin colocar, 0 choques; B 8.322 puntos blandos frente a 118.418 del horario publicado |

### Curso 2026-2027, desde cero ([ADR-039](docs/adr/ADR-039-fidelidad-con-datos-reales-2026-2027.md))

| Qué | Resultado |
| --- | --- |
| Importar XML + GPU | 82 clases, 154 profesores, 96 aulas, 884 lecciones (acoples de hasta 45 líneas), 6 rejillas, 5.582 deseos; XML y GPU dan el mismo colegio |
| Exportar GPU001 | idéntico al de Untis (4.102/4.102 filas, hora 0 incluida) |
| Generar desde cero (A, 45 s) | 2 de 2.429 horas sin colocar, 0 choques, ningún deseo −3 incumplido; 110.709 puntos blandos frente a 142.317 del horario publicado |
| Sección Primaria tecleada desde la interfaz | rejilla, clases, lecciones y deseos introducidos con la Fachada y generados sin choques |

## Uso

**Escritorio** (`schedule-desktop [proyecto]`): arranca en una página de inicio con
un asistente para crear un colegio desde cero y la lista *Primeros pasos*; cinta
con iconos y ventanas como en Untis
—Datos maestros, Rejillas, Deseos, Lecciones, Ponderación, Optimización
(A/B/D/E/Reparar), Evaluación, Diagnóstico (panel), Diálogo de planificación
con arrastrar y soltar, Horarios con formatos, impresión, PDF y HTML— en
español y alemán. Ver [la lista de paridad con Untis](docs/paridad_untis.md).

**Línea de órdenes:**

```powershell
schedule-engine convert untis.xml colegio.rsp          # importar (también GPU, .bjs)
schedule-engine solve colegio.rsp --strategy B -t 600  # generar u optimizar
schedule-engine evaluate colegio.rsp                   # número de evaluación
schedule-engine convert colegio.rsp gpu/               # GPU001.TXT para MiUntisWeb
```

## Entorno de desarrollo

Python 3.14 del sistema.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Los exports reales de Untis contienen datos personales y **no se versionan**:
colócalos en `tests/fixtures/real/` (ignorado por git) y los tests de regresión
los usarán. La CI usa `tests/fixtures/untis_anon.xml`, generado con
`scripts/anonymize_untis.py`.

## Verificación de calidad (obligatoria antes de cerrar cualquier fase)

```powershell
.\.venv\Scripts\python.exe scripts\check.py
```

Ejecuta en orden: `ruff format --check`, `ruff check`, `mypy --strict` y `pytest`.
