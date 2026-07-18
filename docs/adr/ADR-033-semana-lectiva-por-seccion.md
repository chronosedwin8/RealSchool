# ADR-033: Semana lectiva por sección (marcos horarios múltiples)

**Fecha:** 2026-07-18 · **Estado:** Aceptado

## Contexto
En Untis cada **sección** (Kinder/Primaria/Bachillerato) tiene su propia *semana
lectiva*: número de días lectivos, horas de reloj de cada período, corte
Mañana/Tarde y **recreos**. No todas comparten estructura, y al ingresar la carga
se **elige la semana lectiva** de cada lección. El Modelo Canónico, en cambio,
tiene una única `TimeGrid` uniforme (un segmento por día, todos con los mismos
períodos). Necesitábamos soportar varias estructuras horarias sin romper la
rejilla única ni la retro-compatibilidad de los `.bjs` existentes (Fase 7 E3).

## Decisión

### 1. La semana lectiva es un descriptor superpuesto, no una rejilla nueva
La `TimeGrid` sigue siendo el **universo físico único** del solver. Una
`SchoolWeek` (en `application/project.py`) es un descriptor con nombre que se
superpone a ese universo: `days`, `max_periods`, `afternoon_from`, horas de reloj
por período (`SchoolPeriod`) y `breaks` (recreos). Se guarda en `BjsProject.
school_weeks` y se serializa en un archivo aditivo `schoolweeks.json` (los `.bjs`
antiguos siguen abriéndose sin él).

### 2. Efecto en el motor: recorte de `allowed_starts` por clase
Cada lección se **asigna** a una semana lectiva por un atributo entero
`school_week` en sus `Task` (igual patrón que `coupling`, motor-agnóstico y
serializable). El efecto en el solver reutiliza **exactamente** el mecanismo de
disponibilidad (E1): `_effective_problem()` resta, por tarea, los slots que su
semana marca como recreo o por encima del tope de períodos/días. Las clases sin
semana asignada no se ven afectadas → **cero impacto** en proyectos existentes.

### 3. Presentacional vs. estructural
Horas de reloj y corte Mañana/Tarde son **presentacionales** (vista/reportes): no
alteran el modelo del solver. Solo `breaks`, `max_periods` y `days` recortan el
dominio temporal. Esto mantiene el núcleo agnóstico al "reloj" (ADR-004).

### 4. Interfaz
Un módulo **Semana lectiva** edita el marco (rejilla período×franja, recreos por
clic, horas de reloj editables, altas/renombrado/borrado por sección). La **Carga
(lecciones)** gana una columna *Semana lect.* con un combo de las semanas creadas,
como la columna "Semana lect.dif" de Untis. Todo pasa por la Fachada
(`EngineService.add_school_week`, `set_lesson_school_week`, `set_school_week_*`).

## Consecuencias
- **Positivas:** varias estructuras horarias conviviendo sobre una sola rejilla;
  aditivo y retro-compatible; reutiliza el patrón de disponibilidad sin plugin
  nuevo; el núcleo temporal no cambia.
- **Negativas:** al eliminar una semana hay que reindexar el atributo
  `school_week` de las clases (índices por posición). El corte Mañana/Tarde por
  ahora es único (no por día), suficiente para las secciones reales del colegio.
- En español, coherente con el resto del repositorio.
