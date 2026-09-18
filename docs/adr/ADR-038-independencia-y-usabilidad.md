# ADR-038: Independencia total desde la interfaz y usabilidad

**Fecha:** 2026-09-18 · **Estado:** Aceptado

## Contexto

Tras R5 la aplicación replicaba el flujo de Untis sobre datos importados, pero
un colegio que empezara de cero no podía crear su rejilla de tiempo desde la
interfaz: sin rejilla no hay dónde colocar clases. Además, una revisión de la
interfaz con ojos de usuario nuevo encontró: pantalla de inicio vacía, ningún
icono, botones sin explicación, altas escondidas en una fila en blanco,
números ilegibles (`1218418`), texto oscuro sobre colores de materia oscuros y
ningún camino guiado.

## Decisión adoptada

1. **Independencia.** La Fachada crea, copia, renombra y borra rejillas, fija los
   días, añade y quita el último período y genera las horas (duración, cambio de
   clase, recreos). Todo protege los horarios ya colocados: no se borra una
   rejilla en uso ni un período con clases. Un proyecto nuevo trae una rejilla
   "Estándar" lista; una clase nueva recibe la primera rejilla y una lección de
   una sola clase, su aula base (como en Untis). Una prueba recorre un colegio
   entero desde cero solo con la Fachada hasta los horarios de cada clase,
   profesor y aula.
2. **Primer contacto guiado.** Página de inicio con tarjetas (crear, abrir,
   importar, ejemplo), proyectos recientes y la lista **Primeros pasos**: los ocho
   pasos del flujo Untis con su estado real calculado del proyecto y un botón a
   la ventana de cada paso. Asistente de colegio nuevo con vista previa de las
   horas de la jornada.
3. **Iconos explicativos.** Iconos Lucide (licencia ISC, vendorizados en
   `untis_desktop/icons/`, sin dependencia nueva) con **nombres semánticos** y un
   **color por familia de herramienta** (azul archivo/datos, violeta lecciones y
   planificación, verde generar, ámbar avisos, rojo borrar/detener, gris vista).
   Ninguno procede de Untis. Una prueba recorre todas las ventanas y exige icono
   y tooltip explicativo en cada botón y acción.
4. **Ayuda contextual** (F1) por ventana y guía rápida, redactadas desde cero;
   atajos Ctrl+0…9; tooltips con título, atajo y explicación; estado del horario
   siempre visible en la barra de estado.
5. **Legibilidad.** Separador de miles en todas las cifras; color de texto
   calculado por contraste (WCAG) sobre el color de cada materia; nombres de
   criterio legibles en el Diagnóstico; el registro técnico oculto por defecto.

## Consecuencias técnicas

- Quitar un período intermedio no se permite: el número de período es la
  dirección de las clases colocadas. La interfaz propone marcarlo como recreo.
- Las cadenas nuevas (ayuda, pistas, tooltips) están en español y alemán.
