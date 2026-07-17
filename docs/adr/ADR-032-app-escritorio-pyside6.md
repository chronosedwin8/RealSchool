# ADR-032: Arquitectura de la app de escritorio (PySide6)

**Fecha:** 2026-07-17 · **Estado:** Aceptado

## Contexto
La Fase 6 construye el cliente de escritorio: un competidor de Untis que debe
igualarlo en organización y productividad, con 15 módulos. Debe respetar la regla
de oro (toda la lógica en el motor) y arrancar por un MVP vertical usable sobre
datos reales de Untis.

## Decisión

### 1. Paquete separado `scheduling_desktop`, cliente de la Fachada
Nuevo paquete `src/scheduling_desktop/` con entry point `schedule-desktop` y un
extra `desktop` en `pyproject` (`PySide6`, `pytest-qt`). **Solo importa la
Fachada** (`scheduling_platform.application`): nunca `core`/`engine`/`sal`/… Dos
tests de frontera lo verifican (el motor no importa la GUI; la GUI no salta la
Fachada).

### 2. PySide6, con separación estricta UI↔motor
- `main_window.py`: shell (menú/toolbar, dock del Explorer, `QStackedWidget`
  central, barra de estado).
- `engine_bridge.py`: `EngineBridge(QObject)` traduce la Fachada a señales de Qt
  y corre `optimize` en un `SolveWorker(QThread)` que publica progreso en vivo
  vía `on_event`; el botón *Detener* activa el `CancelToken`.
- `models/`: `QAbstractTableModel` sobre los modelos de vista (sin lógica).
- `modules/`: un widget por módulo; se refrescan reaccionando a las señales del
  puente. Ningún módulo llama al motor salvo por `EngineBridge`.

### 3. MVP primero (esqueleto vertical usable)
El primer entregable es un flujo de punta a punta: **Shell + Explorer +
Dashboard + Data Manager (ver + edición básica) + Schedule Editor (vista) +
Optimization Console (progreso + cancelar)**. Los otros módulos (Constraint
Manager, Validation Center, Reports, Import/Export, etc.) crecen después.

### 4. Pruebas headless
Los tests de GUI corren con `QT_QPA_PLATFORM=offscreen` (fijado en `conftest`) y
una única `QApplication` compartida. El worker se prueba de forma determinista
llamando `run()` en el hilo del test. El horario y las tablas se afirman contra
la Fachada, no contra píxeles.

## Consecuencias
- **Positivas:** UI desacoplada y verificable; mypy estricto pasa sobre el código
  Qt (PySide6 trae stubs); MVP usable sobre el `.bjs` real; base lista para los
  15 módulos.
- **Negativas:** PySide6 añade ~250 MB al entorno de escritorio (aislado en el
  extra `desktop`, no afecta al motor headless ni al binario `schedule-engine`).
- En español, coherente con el resto del repositorio.
