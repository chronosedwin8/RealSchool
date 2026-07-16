# ADR-028: Formato de proyecto `.bjs` (contenedor ZIP canónico)

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
La Fase 2 dejó `.schedule` (ZIP con problema canónico + config). La Fase 3 lo
eleva a un **contrato de datos oficial** `.bjs`: portable, íntegro, versionable
con Git e independiente de bases de datos externas, como frontera única del
ecosistema (CLI, GUI futura, solvers).

## Decisión

### 1. Núcleo canónico, no académico
El `.bjs` guarda el **Modelo Canónico** (reusa `problem_to_dict`), no el dominio
académico. Untis (los 4 años reales) va directo a canónico con acoples y
minutos-reloj; no existe forma académica ni `Untis→académico`. Guardar canónico
es universal y no estanca los datos reales. El `academic.json` humano queda como
vista opcional para cuando llegue la autoría por GUI.

### 2. Reparto por capas (respeta la frontera)
- **`serialization/bjs.py` (Core):** contenedor crudo — ZIP DEFLATE, `manifest`
  con firma y **checksums SHA-256**, `pack` atómico (`os.replace`), `read`
  (verifica integridad y versión), `extract` git-friendly (`sort_keys`, indent 2,
  determinista), `pack_dir`, y el **seam de migración** de esquemas. Solo dicts.
- **`application/project.py`:** `BjsProject` tipado — parte el problema en
  `calendar`/`resources`/`tasks` (diffs limpios), interpreta `constraints.json`
  (`PluginsConfig`) y `solver_config.json` (`EngineConfig`), solución, métricas e
  historial. Aquí se conoce la config, por eso no vive en el Core.

### 3. Validación en dos fases, sin jsonschema
- **Estructural:** `check_structure` verifica claves/tipos por archivo antes de
  instanciar, con errores `archivo + campo`.
- **Referencial:** la disparan los constructores ya existentes
  (`SchedulingProblem`, `PluginsConfig.validate`); `check_consistency` añade los
  cruces entre archivos (la solución referencia tareas/recursos existentes) y
  avisos blandos (recursos sin uso). Coherente con la política "sin Pydantic".

### 4. CLI `schedule-engine project [info|validate|extract|pack]`
Operaciones de contenedor en el binario único. `project validate` valida el
**contrato de datos** (distinto del `validate` de factibilidad). `extract`/`pack`
habilitan el flujo de Git (editar los JSONs, re-empaquetar atómicamente).

## Consecuencias
- **Positivas:** un artefacto por proyecto, versionable, íntegro y auto-contenido;
  round-trip sin pérdida verificado con Hypothesis (split/merge + ciclo de Git);
  seguro ante corrupción (checksums) e interrupciones (atomicidad); migración
  lista para durar. Verificado en el binario real sobre Untis (2023-2024).
- **Supersede** a `.schedule` (días de antigüedad, sin usuarios): los comandos de
  Fase 2 pasaron a `.bjs` sin capa de compatibilidad.
- Los JSON Schemas formales publicables quedan como opción para la Fase 4 (SDK /
  interop externo), no como validación interna.
