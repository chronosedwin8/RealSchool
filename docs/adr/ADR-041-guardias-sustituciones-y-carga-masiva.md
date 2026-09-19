# ADR-041: Guardias de recreo, sustituciones y carga masiva de datos

**Fecha:** 2026-09-18 · **Estado:** Aceptado

## Contexto

Con el horario ya resuelto, un colegio seguía necesitando Untis (u otra
herramienta) para dos cosas que dependen del horario y ocurren todas las
semanas: repartir la vigilancia de los recreos y organizar las sustituciones
cuando falta un profesor. El inventario de funciones de Untis
(`docs/referencia_untis.md`) sitúa las sustituciones como la carencia más
grave: sin ellas hay que abrir Untis cada día lectivo.

Había además una barrera al empezar de cero: los datos maestros solo se podían
teclear fila a fila. Un colegio real tiene 154 profesores, 96 aulas y 884
lecciones.

## Decisión adoptada

1. **Guardias de recreo** (`untis_model/supervision.py`,
   `heuristic/supervision.py`, ventana Guardias). Un turno es zona + día +
   recreo, con su profesor. El reparto automático solo propone a quien da clase
   justo antes o justo después del recreo (está en el centro), respeta el tope
   semanal de minutos de cada profesor (`Teacher.supervision_max`, el "PA-Max"
   de Untis), no toca los turnos puestos a mano y equilibra los minutos entre
   todos. Es voraz con mejora local, determinista por semilla y sin OR-Tools:
   el problema es pequeño y la capa `heuristic` es pura.
2. **Sustituciones** (`untis_model/substitution.py`, `untis_model/daily.py`,
   ventana Sustituciones). El horario es semanal y una ausencia es de fechas:
   `daily.py` es el paso de la semana al día (festivos, día de la semana,
   lecciones vigentes). Una ausencia puede ser de profesor, clase o aula, de
   varios días y acotada por horas en el primero y el último. Para cada clase
   afectada se proponen sustitutos ordenados: se descarta a quien está ocupado,
   ausente, de guardia o con reserva 9; y entre los demás gana quien ya está en
   el centro, luego quien da esa materia o ese grupo, luego quien menos
   sustituciones lleva y por último la reserva 0-8. Cada candidato trae escrita
   la razón de su puesto, porque quien organiza el parte tiene que poder
   defender la decisión.
3. **Contadores** por profesor, con el criterio de Untis: suman la sustitución
   y el servicio extra; no suman la supresión ni el cambio de aula.
4. **Carga masiva** (`interop/tabular.py`, `application/untis/bulk.py`): CSV y
   TSV con el delimitador y la codificación deducidos, encabezados por nombre
   técnico o por la etiqueta en español o alemán, y copiar/pegar desde una hoja
   de cálculo. La importación es **parcial**: las filas buenas entran y las
   malas se explican una a una; una fila nunca entra a medias y todo es un solo
   paso de deshacer. Exportar e importar el mismo formato permite editar en
   Excel y volver.
5. Los tres módulos entran en la Fachada como **mixins** en ficheros propios:
   `UntisService` ya era grande y cada módulo tiene su vocabulario.

## Consecuencias

- Datos nuevos en el proyecto: zonas y turnos de guardia, festivos, ausencias y
  decisiones del día; el profesor gana minutos de guardia y reserva para
  sustituir, y la clase su profesor tutor (que ya venía en el GPU003 y se
  perdía). Todo se guarda en el `.rsp`.
- El XmlInterface de Untis no lleva nada de esto, así que no viaja en el XML;
  se queda en el proyecto de RealSchool.
- Falta la publicación a profesores y alumnos (portal o app) y el horario
  individual por alumno (Kursplanung), que siguen fuera del alcance.

## Comprobado de punta a punta

Un colegio entero creado desde cero solo con la Fachada, sin ningún dato de
Untis: 12 profesores, 8 materias, 6 aulas y 6 clases pegados desde una hoja de
cálculo; 48 lecciones cargadas de una tabla; marco horario de la 1ª a la 7ª
hora; horario generado con la estrategia A en 20 s con 0 horas sin colocar, 0
choques y ninguna colocación fuera del marco; zona de vigilancia con sus 5
turnos repartidos; y una ausencia de un profesor resuelta con el primer
candidato propuesto ("ya está en el centro, da clase al grupo, 0
sustituciones").

Sobre los datos reales de 2026-2027: 15 turnos de guardia (3 zonas x 5 días)
repartidos entre 15 profesores con 20 minutos cada uno, y una ausencia de un
lunes que deja 9 clases afectadas, todas con candidatos ordenados.

El Diagnóstico hizo su trabajo durante esta prueba: con el marco horario de la
1ª a la 6ª hora se negó a optimizar porque cada clase necesitaba 26 horas y
solo tenía 25 abiertas.
