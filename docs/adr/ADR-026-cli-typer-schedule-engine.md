# ADR-026: CLI profesional `schedule-engine` (Typer)

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
Con la Capa de Aplicación (ADR-024), el formato `.schedule` (ADR-025), la config
(H3) y los casos de uso núcleo ya construidos, faltaba la **capa de entrada**: un
ejecutable que un humano o un CI puedan invocar.

## Decisión

### 1. `cli/` sobre Typer, delgada por diseño
`scheduling_platform/cli/main.py` expone la app Typer `schedule-engine`. Cada
subcomando (`convert`, `generate`, `optimize`, `validate`, `explain`, `doctor`,
`config validate`) **solo** parsea argumentos, construye el `Command` de la Capa
de Aplicación y lo entrega al `CommandDispatcher`, propagando su exit code con
`typer.Exit`. La CLI **no contiene lógica de negocio** y no toca el Core.

### 2. `doctor` reutiliza la Fase 1
`DoctorCommand` reporta Python/hardware/paquetes vía `Provenance.capture()` (del
framework de benchmarking) y detecta los solvers disponibles instanciándolos con
`solver_factory_for` — sin lógica de detección nueva.

### 3. Dependencias en un extra `cli`
`typer` y `rich` van en `[project.optional-dependencies].cli` (y `dev`), de modo
que instalar el Core no arrastra la CLI. Punto de entrada:
`schedule-engine = scheduling_platform.cli.main:app`.

## Consecuencias
- **Positivas:** ejecutable real y probado (`CliRunner`); `schedule-engine doctor`
  verificado en el binario instalado (JSON limpio a stdout, 4 solvers detectados).
  El contrato de streams se hereda del dispatcher, sin duplicarlo.
- **Limitación conocida (no del CLI):** en problemas *degenerados* (un recurso con
  una sola tarea) el modelo compacto no materializa `tstart` porque no se genera
  no-solape, y la extracción falla. No afecta a instituciones reales (siempre hay
  recursos con varias clases); se documenta y se deja el Core intacto (contrato de
  Fase 2). Revisable como endurecimiento futuro del Core.
- `new` y `clean` (plantillas y limpieza de cachés) quedan como incrementales;
  el flujo real de entrada es `convert` (importar datos reales) + `optimize`.
