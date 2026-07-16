# ADR-025: Formato de proyecto unificado `.schedule`

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
Un proyecto escolar real necesita albergar en un solo lugar el problema, la
configuración, el último horario y las trazas de benchmarking. El formato plano
`.proschedule` (JSON gzip) guarda problema+solución, pero no un proyecto completo
multi-archivo.

## Decisión

### 1. `.schedule` = contenedor ZIP
Al estilo de los documentos ofimáticos modernos, un `.schedule` es un ZIP con:

```
project.json       metadatos (UUID, nombre, fecha, versión del motor)
problem.json       problema canónico serializado
config.yaml        pesos / solvers / flags (tipado fuerte en H3)
solution.json      último horario (opcional)
benchmarks/*.json  trazas de telemetría local
```

`ScheduleProject` lo modela; `open_project`/`save_project`/`new_project` lo operan.

### 2. Reutilización, no reimplementación
El contenido de `problem.json`/`solution.json` usa los codecs de dominio ya
existentes (`serialization/codec.py`: `problem_to_dict`, `solution_to_dict`, y sus
inversos). El formato no duplica la serialización del modelo canónico.

### 3. Escritura atómica
`save_project` serializa el ZIP en memoria (`io.BytesIO`), lo escribe a un
temporal en el **mismo directorio** y hace `os.replace(tmp, destino)` — atómico
dentro del mismo volumen. Un corte de energía deja el original intacto (nunca un
archivo a medio escribir). `open_project` lee el ZIP **en memoria** (no extrae a
disco), sin dejar temporales.

## Consecuencias
- **Positivas:** un único artefacto por proyecto, versionado y auto-contenido;
  round-trip sin pérdida (verificado por test); seguro ante fallos de E/S.
- `.proschedule` se conserva como formato plano interno; `.schedule` es el
  contenedor de proyecto de cara al usuario y a la GUI futura.
- `config` se guarda como dict YAML en H2; H3 le dará tipos fuertes (`EngineConfig`
  / `PluginsConfig`) sin cambiar el formato del archivo.
