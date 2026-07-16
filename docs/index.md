# RealSchool — SDK del Motor de Horarios

Motor **genérico** de calendarización por restricciones, construido sobre Google
OR-Tools CP-SAT detrás de una **Solver Abstraction Layer**, con un CLI headless
(`schedule-engine`) y un formato de proyecto atómico y versionable, `.bjs`.

Esta documentación no solo describe la API: explica el **modelo mental**, los
**contratos** y los **puntos de extensión**, para que puedas crear una restricción,
un importador, un exportador o un solver **sin tener que preguntar nada**.

## Cómo está organizada

<div class="grid cards" markdown>

- **Arquitectura** — el modelo mental y el flujo de datos completo, del importador
  al solver y de vuelta al `.bjs`.
- **Guías del SDK** — how-to de extensión: restricciones (HARD/SOFT + Tiers),
  objetivos, importadores, exportadores, solvers (`ISolver`) y telemetría.
- **Tutoriales** — un curso progresivo de cuatro niveles, del *hello world* a
  publicar un plugin.
- **Referencia de API** — autogenerada desde el código: siempre al día.
- **Ejemplos** — proyectos ejecutables con `schedule-engine`, sin modificaciones.

</div>

## Principios que verás por todas partes

- **El dominio no conoce el solver.** En todo el repositorio hay una sola línea
  `import ortools`, dentro de `sal/ortools_solver.py`, verificada por tests.
- **Dependencias solo hacia abajo.** `academic → core → dsl → cir → sal`; la capa
  de aplicación y la CLI son clientes, nunca al revés.
- **Contratos explícitos y probados.** Cada extensión (plugin, solver, importador)
  implementa una interfaz pequeña con un contrato verificable.

## Instalación rápida

```bash
pip install -e ".[cli]"
schedule-engine doctor
```

`doctor` reporta el entorno y los solvers disponibles (CP-SAT, CBC, SCIP, HiGHS).

!!! tip "Todo offline"
    Este sitio se genera con `mkdocs build --strict` y se abre directamente con
    `file://.../site/index.html`, sin servidor: búsqueda, temas claro/oscuro y
    diagramas incluidos.
