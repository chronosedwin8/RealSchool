# ADR-024: Capa de Aplicación, Command Dispatcher y contrato de proceso

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
La Fase 2 convierte el motor validado en un producto ejecutable desacoplado. Para
que cualquier cliente (GUI Qt/Tauri, script, CI) lo consuma como un proceso más
—sin acumular lógica de negocio— hace falta una frontera rígida entre la entrada
(CLI) y la API pública del `SchedulingEngine`.

## Decisión

### 1. Nueva Capa de Aplicación (`scheduling_platform/application/`)
Se interpone entre la CLI y el motor. Contiene el patrón **Command** (cada caso de
uso es un objeto con `execute(ctx) -> CommandResult`), un `AppContext` con las
dependencias inyectadas (solver factory, logger, formato) y un `CommandDispatcher`
que compone todo. Añadir una operación = añadir un archivo de comando (Abierto/
Cerrado); el dispatcher y el parser no se tocan.

### 2. Frontera infranqueable, verificada por test
El Core de optimización (`core`, `academic`, `sal`, `plugins`, `pipeline`,
`engine`, `dsl`, `cir`) **nunca** importa `application` ni `cli`. Se añade un test
a `tests/test_architecture.py` que recorre el árbol y falla ante cualquier
violación (igual que la regla "solo la SAL importa ortools").

### 3. Contrato de streams y exit codes, garantizado por construcción
- Los comandos **nunca** escriben en `stdout`: devuelven un `payload` y el
  dispatcher lo serializa (JSON/YAML) a `stdout`. El logger escribe **siempre** a
  `stderr`. Así `comando > out.json` no puede filtrar trazas (Zero-Leakage).
- Cada `AppError` lleva su exit code: `0` éxito, `1` config/parámetros, `2`
  inviable, `3` timeout, `4` interno. El dispatcher traduce **cualquier**
  excepción a un código estable; nada escapa del proceso sin código.

## Consecuencias
- **Positivas:** clientes en cualquier lenguaje vía proceso + streams; el Core
  queda intacto; la disciplina de I/O es estructural, no una convención frágil.
- **Sin Pydantic** (coherente con ADR-021): la validación de config (H3)
  reutilizará dataclasses + `registry_from_catalog`, no un framework nuevo.
- La CLI concreta (Typer/rich) y el `--json-stream` llegan en H5 y H12; H1 deja
  lista la maquinaria de despacho.
