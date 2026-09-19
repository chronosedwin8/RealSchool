# Referencia de funciones de Untis (para paridad con RealSchool)

Este documento es un resumen propio, elaborado a partir de documentación pública
de Untis (untis.at/manual, help.untis.at, platform.untis.at, webhelp.untis.at y
guías de distribuidores como pedav.de y gpuntis.ch), pensado únicamente para
decidir qué funciones le faltan a RealSchool respecto de Untis. No es una copia
de los textos ni de los iconos de Untis: está redactado con palabras propias y
solo se citan literalmente, entre comillas, nombres de campo o términos en
alemán cuando hace falta identificar la función sin ambigüedad. Donde la
documentación pública no da suficiente detalle, se indica explícitamente.

La columna "Nota para RealSchool" compara con el estado del repositorio en la
rama `untis-refactor` (ver `docs/paridad_untis.md`, `src/scheduling_platform` y
`src/untis_desktop`), no con una versión futura.

## 1. Stundenplanung (planificación de horarios)

### 1.1 Datos maestros: Klassen (clases)

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Kürzel / Langname | Nombre corto y largo únicos de la clase | Stammdaten > Klassen | Implementado (clases con código y nombre) |
| Klassenlehrer (Ord) | Profesor tutor de la clase | Ficha de la clase | Existe el concepto de tutor en el modelo |
| Abteilung | Asigna la clase a un departamento para filtrar e imprimir | Ficha de la clase | Implementado (`SchoolClass.department`, columna Departamento) |
| Studentengruppen | Subgrupos de alumnos dentro de la clase (optativas) | Kursplanung / Unterricht | No implementado (ver Kursplanung, módulo 4) |
| Zeitwünsche -3..+3 | Preferencia u obligación horaria por celda o día | Klassen > Zeitwünsche | Implementado (`RequestsWindow`, deseos -3..+3) |
| Kernzeit (+3 en primeras horas) | Marca las horas en que la clase debe tener clase sí o sí | Zeitwünsche | Implementado como caso extremo del deseo +3 |
| Min/max horas por día | Límite de carga diaria de la clase | Ficha de la clase | Cubierto por ponderación `class_periods_per_day` |
| Mittagspause min-max | Duración aceptable del descanso de mediodía | Ficha de la clase / Zeitraster | Cubierto por `class_lunch_break` |
| Nachmittagsunterricht | Si la clase puede tener clases por la tarde | Ficha de la clase | Cubierto por `class_afternoon_periods` |
| Farbe | Color de la clase en los horarios impresos | Ficha de la clase | No implementado; el color va por materia (`Subject.back_color`) |

### 1.2 Datos maestros: Lehrer (profesores)

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Kürzel / nombre / apellido | Identificación del profesor | Stammdaten > Lehrer | Implementado |
| Número de personal, SAP, alias | Datos administrativos para exportar/imprimir | Ficha del profesor | No relevante sin integración con nómina |
| Abteilung (múltiple) | Asignación a uno o varios departamentos | Ficha del profesor | Implementado con un departamento por profesor, no varios |
| Email / teléfono / móvil | Contacto, usado por el módulo Info-Stundenplan | Ficha del profesor | No implementado (no hay módulo de aviso) |
| Fecha de nacimiento, escuela base | Informativo, para impresiones | Ficha del profesor | No relevante para la planificación |
| Fechas de alta/baja en el curso | Limita el periodo en que el profesor da clase | Ficha del profesor | No confirmado como campo propio |
| Género | Usado por la optimización de Pausenaufsichten | Ficha del profesor | No aplica: Pausenaufsichten no existe (módulo 2) |
| Zeitwünsche -3..+3 y Kernzeit | Igual que en clases, pero para el profesor | Lehrer > Zeitwünsche | Implementado |
| Min/max horas por día/semana, huecos | Límites de carga y huecos (Hohlstunden) | Ficha del profesor | Cubierto por ponderación `teacher_*` |
| "PA-Max" / "PA (Ist)" | Tope semanal de minutos de vigilancia de recreo y minutos ya asignados | Pausenaufsichten > Lehrer | No implementado (módulo Pausenaufsichten ausente) |
| "Sperrvermerk" (0-9) | Restricción de uso del profesor como sustituto; 9 = prohibido | Vertretungsplanung > Lehrer | No implementado (módulo Vertretungsplanung ausente) |
| Indicador de estadística (p. ej. "F" externo, "T" tiempo parcial) | Clasifica al profesor para el Vertretungsvorschlag | Ficha del profesor | No implementado |

### 1.3 Datos maestros: Räume (aulas), Fächer (materias) y Abteilungen

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Kürzel / Langname / capacidad | Identificación y aforo del aula | Stammdaten > Räume | Implementado (aulas con capacidad) |
| Cadena de aulas alternativas | Aulas intercambiables por capacidad o tipo | Ficha del aula | Implementado (cadena de alternativos) |
| "Gänge" (hasta dos pasillos) | Ubica el aula junto a un pasillo para Pausenaufsichten | Ficha del aula | No implementado (depende del módulo 2) |
| Abteilung del aula | Agrupa aulas por departamento para imprimir | Ficha del aula | Implementado (`Room.department`) |
| "(H)" Hauptfach | Marca una materia como principal | Stammdaten > Fächer | Implementado (materias principales) |
| "(F)" Freifach, "(R)" Randstundenfach | Materia optativa / apta solo en horas de borde | Ficha de la materia | No confirmado en detalle |
| Fachraum | Aula obligatoria para la materia (p. ej. gimnasio) | Ficha de la materia | Cubierto por `subject_required_room` |
| "Hauptf./Tag" | Máximo de materias principales por día en una clase | Ficha de la materia / Klassen | Cubierto por `main_subject_per_day_max` |
| "Nachm.St." | Si la materia puede darse por la tarde | Ficha de la materia | No confirmado como campo propio |
| Fachfolge | Orden o secuencia deseada entre materias | Ficha de la materia | Cubierto por `subject_sequence` |
| Abteilungen (departamentos) | Agrupación transversal de clases/profesores/aulas para imprimir y filtrar | Stammdaten > Abteilungen | No implementado |

### 1.4 Zeitraster (rejilla de tiempo) y pausas

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Zeitraster estándar | Días, horas por día, límite mañana/tarde | Inicio > Zeitraster | Implementado (rejillas de tiempo editables) |
| "Tageszeitraster" | Horario distinto por día de la semana (activable) | Configuración > Zeitraster > Días | No implementado: cambia las horas de reloj por día, no qué horas existen (ADR-040) |
| Mittagspausen | Rango de horas en que puede caer el descanso y su duración | Zeitraster > Pausas | Implementado como recreos detectados/editables |
| Máximo de clases con descanso simultáneo | Limita cuántas clases comen a la vez (comedor) | Ponderación > Klassen | No confirmado como criterio propio |

### 1.5 Zeitwünsche (deseos de tiempo) -3 a +3

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Escala -3..+3 por celda | -3 bloqueo absoluto, +3 obligatorio (Kernzeit), -2..+2 preferencia blanda | Zeitwünsche de cada elemento | Implementado igual (escala -3..+3) |
| Aplicable a Klassen, Lehrer, Räume, Fächer | Cada tipo de dato maestro tiene su propia rejilla de deseos | Stammdaten > elemento > Zeitwünsche | Implementado para clases y profesores; a confirmar para aulas/materias |
| Deseo por lección concreta | Además del deseo del elemento, se puede fijar por lección | Unterricht > Zeitwünsche | A confirmar |
| Deseos "no especificados" (p. ej. "2 tardes libres") | Pide un total sin fijar qué día exacto | Zeitwünsche > no especificados | Implementado (`set_unspecified`) |
| Kernzeit | La suma de horas en +3 no puede superar el total de horas del elemento | Zeitwünsche | Implementado como regla del motor |

### 1.6 Unterricht: Kopplungen, Doppelstunden y bloques

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Kopplung (acople) | Varios profesores y/o clases comparten la misma lección simultánea | Unterricht > Koppeln | Implementado (acoplar/desacoplar líneas) |
| Doppelstunde flexible | Permite que el algoritmo elija el par de horas (0-1, 1-2, etc.) | Unterricht > Doppelstunde | Implementado (petición de dobles) |
| Bloque de N horas | Columna "Block" con tamaños separados por coma (p. ej. "3,3") | Unterricht > Block | Implementado (petición de bloques) |
| Combinar bloque y doble | Un bloque de 6 horas repartido en dos bloques de 3 | Unterricht > Block | A confirmar si se admite la combinación exacta |

### 1.7 Gewichtung (ponderación)

Untis organiza la ponderación en pestañas temáticas con deslizadores de seis
posiciones (0 "unwichtig" a 5 "extrem wichtig"); el manual advierte de que el
salto de 4 a 5 es muy grande y de no poner muchos criterios en 5 a la vez. La
documentación pública detalla en profundidad la pestaña de clases; para las
pestañas de profesores, aulas y materias solo se listan nombres generales de
criterio, no el enunciado completo de cada deslizador (límite de la
documentación pública).

| Pestaña en Untis | Criterios documentados públicamente | Nota para RealSchool |
| --- | --- | --- |
| Lehrer (dos pestañas) | Huecos (Hohlstunden), máximo/mínimo de horas por día, descanso de mediodía, tarde aislada, equilibrio de carga | RealSchool tiene `TEACHERS_1`/`TEACHERS_2` con 11 criterios equivalentes |
| Klassen | Evitar huecos, min/max horas/día, descanso de mediodía, secuencia de materias (Fachfolge), máximo de materias distintas/día, tutor al menos una vez al día, tope de clases con descanso simultáneo | RealSchool tiene `CLASSES` con 5 criterios (falta tutor-al-día y tope simultáneo) |
| Fächer | Doble hora, bloques, no el mismo día, no días consecutivos, secuencia, aula obligatoria | RealSchool tiene `SUBJECTS` con 6 criterios equivalentes |
| Hauptfächer | Materias principales por día, no consecutivas, preferencia por la mañana | RealSchool tiene `MAIN_SUBJECTS` con 4 criterios equivalentes |
| Räume | Optimización de asignación, capacidad, cadena de alternativos | RealSchool tiene `ROOMS` con 3 criterios equivalentes |
| Distribución de horas | Mismo día, reparto uniforme en la semana, mismo periodo en días consecutivos, primera/última hora | RealSchool tiene `PERIOD_DISTRIBUTION` con 5 criterios |
| Zeitwünsche | Peso del deseo de profesor/clase/aula/materia y de los no especificados | RealSchool tiene `TIME_REQUESTS` con 5 criterios |
| Analyse | Panel de solo lectura para revisar el efecto de cada deslizador tras optimizar | RealSchool tiene la pestaña `ANALYSIS` |

### 1.8 Optimierung (optimización automática)

| Estrategia | Qué hace | Cuándo usarla | Nota para RealSchool |
| --- | --- | --- | --- |
| A | La más rápida; no da el mejor resultado pero es ideal para detectar errores en los datos de entrada | Primera pasada, para depurar datos | Implementado (`Strategy.A`, uso equivalente) |
| B | Resultado ya bueno en tiempo moderado; se ajustan los deslizadores de ponderación después de verla | Segunda pasada, tras limpiar errores con A | Implementado (`Strategy.B`) |
| C | Mencionada en el título de la página de manual ("A, B, C, D, E") pero sin descripción propia en las fuentes consultadas | No documentado con suficiente detalle público | No implementado; posible versión antigua o interna |
| D | Reparto progresivo por porcentaje de clases (empieza p. ej. en 30% y sube de 20 en 20); mejor que B en algunos colegios pero más lenta | Después de calibrar la ponderación con B | Implementada (`heuristic.Strategy.D`) |
| E | La más lenta ("optimización nocturna"); suele dar el mejor resultado | Al final, tras probar las demás | Implementada (`heuristic.Strategy.E`) |
| I | Aparece en el encargo de esta investigación pero no se encontró ninguna página oficial que la describa | No documentado en absoluto en las fuentes consultadas | Sin equivalente conocido |
| Filtros de la optimización | Rango de clases, área, duración mínima, grupo semanal (horario multisemana) | Diálogo de optimización | A confirmar cobertura completa |

### 1.9 Diagnose (diagnóstico)

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Diagnose Eingabedaten | Detecta inconsistencias en los datos antes de generar el horario (p. ej. horas que no caben en los días libres de un profesor) | Panel Diagnose, antes de optimizar | Implementado (diagnóstico de datos de entrada) |
| Diagnose Stundenplan | Compara el horario generado con los datos y muestra las violaciones (deseos de tiempo, horas de más o de menos) | Panel Diagnose, después de optimizar | Implementado (diagnóstico tras generar) |
| Salto directo al conflicto | Un clic en el diagnóstico muestra las horas afectadas en el horario | Panel Diagnose | Implementado (doble clic salta a la lección) |

### 1.10 Planungsdialog (edición manual)

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Verplanen / entplanen | Colocar o quitar una sesión del horario a mano | Planungsdialog | Implementado (mover y desprogramar) |
| Fixieren | Fijar una sesión para que la optimización no la mueva | Planungsdialog | Implementado |
| Verschieben / tauschen | Mover o intercambiar sesiones viendo destino y coste | Planungsdialog | Implementado |
| Resumen de horas anuales | Muestra cuántas horas faltan por colocar en total y en la semana | Planungsdialog | No confirmado (RealSchool usa barra de suma de carga) |

### 1.11 Formatos de horario e impresión

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Stundenplanformate | Catálogo de formatos con nombre corto y largo (por clase, profesor, aula, general) | Stundenplan > Stundenplanformate | Implementado (formatos por clase/profesor/aula) |
| Impresión en HTML | Publica el horario en HTML de un clic, para intranet o web | Stundenplan > Druck | Implementado (exportación HTML) |
| Impresión en PDF | Genera PDF en vez de papel, apto para email | Stundenplan > Druck | Implementado (exportación PDF) |
| Modo de minutos / horas de inicio-fin | Muestra hora exacta de inicio y fin de cada periodo | Layout del formato | A confirmar |

## 2. Pausenaufsichten (vigilancia de recreos)

Este módulo no aparece en el código de RealSchool (no hay rastro de
"Vertretung", "Pausenaufsicht", "Absenz" ni "Aufsicht" en `src/`), por lo que
toda la sección es una carencia frente a Untis.

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Aufsichtsbereich | Agrupa las vigilancias por zona del colegio | Pausenaufsichten > Aufsichtsbereich | No implementado |
| "Gänge" en el aula | Ubica cada aula junto a los pasillos que vigila una guardia | Stammdaten > Räume | No implementado |
| "PA-Max" / "PA (Ist)" del profesor | Tope semanal de minutos de vigilancia y minutos ya asignados; en rojo si se supera | Stammdaten > Lehrer | No implementado |
| Definir una vigilancia | Asigna un profesor a un recreo y una zona concretos, a mano o por optimización | Pausenaufsichten | No implementado |
| Optimización de Pausenaufsichten | Asigna el profesor más adecuado a cada vigilancia libre según la ponderación; no toca las ya asignadas | Pausenaufsichten > Optimierung | No implementado |
| Filtros de la optimización | Área concreta, rango de recreos, duración mínima (p. ej. solo desde 15 minutos), grupo semanal | Diálogo de optimización | No implementado |
| Orden recomendado | Optimizar primero los recreos largos (más difíciles) y luego los cortos | Manual de Untis (recomendación de uso) | No aplica |
| Ponderación de Pausenaufsichten | Ajusta qué criterios pesan más al elegir profesor (no se encontró el listado completo de criterios en las fuentes consultadas) | Pausenaufsichten > Gewichtung | No documentado con detalle suficiente; no implementado |
| Informes de vigilancia | Listados imprimibles por profesor o por zona | Pausenaufsichten > Listas | No documentado en detalle; no implementado |

## 3. Vertretungsplanung (sustituciones)

Tampoco tiene equivalente en el código actual de RealSchool: no existe gestión
de ausencias diarias ni de sustitutos. Es la carencia más importante para que
un colegio deje de depender de Untis en el día a día.

| Función en Untis | Para qué sirve | Dónde está en Untis | Nota para RealSchool |
| --- | --- | --- | --- |
| Absenzen de profesor/clase/aula | Registra que un profesor, clase o aula no está disponible en un rango de fecha/hora | Vertretungsplanung > Absenzen | No implementado |
| "Grund" (motivo de ausencia) | Motivo configurable que afecta si la ausencia cuenta en el Vertretungszähler | Absenzen > Absenzgründe | No implementado |
| Vertretungsvorschlag | Lista de profesores candidatos a sustituir, ordenada por idoneidad | Vertretungsplanung > Vertretungsvorschlag | No implementado |
| "Merker" | Puntuación de cada candidato: cuánto encaja la sustitución en su horario y distancia a su siguiente clase regular | Vertretungsvorschlag | No implementado |
| Criterios del Vertretungsvorschlag | Si conoce la clase, si tiene la habilitación en la materia, cuántas sustituciones recientes lleva, "Sperrvermerk" (0-9, 9 = prohibido), campo de estadística ("F" externo, "T" parcial); admite criterios propios | Vertretungsplanung > Kriterien | No implementado; el algoritmo de puntuación exacto no está documentado con fórmula pública |
| Vertretungszähler | Contabiliza todas las desviaciones del horario regular (sustituciones, Sondereinsatz y Pausenaufsicht suman; liberaciones y Entfall restan) | Vertretungsplanung > Vertretungszähler | No implementado |
| Configuración del Vertretungszähler | Elige qué eventos cuentan y si solo cuentan las ausencias con motivo asignado; reglas distintas según país/tipo de colegio | Einstellungen > Vertretungszähler | No documentado con la fórmula exacta por país; no implementado |
| Vertretung | Sustitución estándar: un profesor libre cubre al ausente | Vertretungsplanung | No implementado |
| Betreuung | Un profesor supervisa otra clase además de la suya, cuyo titular está ausente | Vertretungsplanung | No implementado |
| Entfall | La clase se suspende porque no se encontró sustituto | Vertretungsplanung | No implementado |
| Verlegung | La clase se traslada a otra hora | Vertretungsplanung | No implementado |
| Tausch | Intercambio de horas entre dos profesores | Vertretungsplanung > Planungsdialog | No implementado |
| Sondereinsatz | Clase espontánea que no estaba en el horario regular | Vertretungsplanung | No implementado |
| Eigenverantwortliches Arbeiten | Los alumnos trabajan de forma autónoma sin profesor sustituto | Vertretungsplanung | No implementado |
| Raumvertretung | Cuando un aula se marca ausente, las lecciones afectadas se resuelven buscando otra aula (por capacidad, ocupación, compatibilidad de bloque, distancia de pasillo) | Vertretungsplanung > Raumvertretung | No implementado (RealSchool sí tiene cadena de aulas alternativas para planificación, pero no para sustituciones del día) |
| Listas y publicación | Listados de sustituciones del día y su distribución a profesores/alumnos | Vertretungsplanung / WebUntis | No documentado en detalle el mecanismo de publicación; no implementado |

## 4. Otros módulos de Untis (mapa, sin profundizar)

| Módulo | Para qué sirve | Nota para RealSchool |
| --- | --- | --- |
| Kursplanung | Planifica cursos optativos de secundaria superior: cada alumno tiene su propio horario y el módulo busca minimizar huecos entre las materias elegidas | No implementado; requeriría el concepto de Studentengruppen/Schülergruppen |
| Unterrichtsplanung und Wertrechnung (Werteinheiten) | Contabiliza la carga de cada profesor más allá de dar clase (dirección, tutoría, gestión de laboratorio, etc.) en "Werteinheiten" para RR. HH. | No implementado; es un módulo administrativo, no de horario |
| Mehrwochenstundenplan | Horarios con ritmos de varias semanas (p. ej. quincenal) | No implementado |
| Perioden (horario por periodos) | Divide el curso en periodos independientes, cada uno con su propio horario y datos maestros | No implementado |
| MultiUser | Varias personas (planificador de horarios y de sustituciones) trabajan a la vez sobre los mismos datos | No implementado; RealSchool es de un solo usuario/proyecto local |
| WebUntis | Acceso por navegador o app móvil al horario personal y al parte de sustituciones | No implementado; RealSchool no publica horarios a alumnos/profesores |
| Info-Stundenplan | Distribución del horario por monitores, correo o web (módulo más antiguo, hoy solapado por WebUntis) | No implementado |
| Kalenderjahr / Terminplanung (Ferien, Schuljahreskalender) | Define días no lectivos y eventos del curso; afecta al cálculo de sustituciones y de Werteinheiten | Existen rejillas de tiempo y recreos, pero no un calendario de días no lectivos ni de eventos |

## Lo mínimo para que un colegio no dependa de Untis

Lista priorizada, de más a menos crítico:

1. Datos maestros completos (clases, profesores, aulas, materias) con sus
   indicadores básicos ("H" principal, capacidad, cadena de alternativos).
2. Rejilla de tiempo con recreos y límite mañana/tarde.
3. Generación automática de horario con ponderación ajustable y al menos dos
   niveles de esfuerzo (rápido para depurar, lento para el resultado final).
4. Diagnóstico de datos antes y de horario después de optimizar.
5. Edición manual del horario con deshacer, fijar y mover sesiones.
6. Impresión y exportación por clase, profesor y aula (HTML/PDF).
7. Gestión diaria de ausencias y sustituciones (Vertretungsplanung): sin esto,
   el colegio necesita otra herramienta o Untis todos los días lectivos. Es la
   carencia más grave detectada en este análisis.
8. Vigilancia de recreos (Pausenaufsichten): asignación y reparto equitativo
   entre el profesorado.
9. Publicación del horario y de las sustituciones a profesores y alumnos
   (portal o app, aunque sea sencillo).
10. Calendario de días no lectivos y eventos del curso.
11. Multiusuario, solo si varias personas deben planificar a la vez.
12. Kursplanung (cursos optativos con horario individual por alumno), solo
    para secundaria superior con oferta de optativas.
13. Werteinheiten/Wertrechnung (contabilidad de carga docente para RR. HH.),
    solo si el colegio necesita ese cálculo y no lo hace ya en otro sistema.

## Fuentes

- https://www.untis.at/manual/optimierungsstrategienke.htm
- https://www.untis.at/manual/opoptimierungs-strategie_a__b__c.htm
- https://www.untis.at/manual/opstrategie_b_-_aufwaendige_opti.htm
- https://help.untis.at/hc/de/articles/360009307840-Optimierungsstrategien
- https://www.untis.at/manual/opgewichtung.htm
- https://www.untis.at/manual/gewichtungke.htm
- https://www.untis.at/manual/opkarteikarte_klassen.htm
- https://www.untis.at/manual/ahkernzeit.htm
- https://www.untis.at/manual/ulkernzeiten.htm
- https://www.untis.at/manual/zeitwuensche_fuer_klassenke.htm
- https://help.untis.at/hc/de/articles/360009300740-Klassen-in-Untis
- https://help.untis.at/hc/de/articles/360009220300-Bedingungen-fuer-Stammdaten
- https://help.untis.at/hc/de/articles/360009211320-Stammdaten
- https://www.untis.at/manual/sd_karteikarte_lehrer.htm
- https://www.untis.at/manual/sd_raeume.htm
- https://help.untis.at/hc/de/articles/7492203339164-WebUntis-Termin-Stammdaten-Raeume
- https://untis-baden-wuerttemberg.de/wp-content/uploads/2018/06/raumlogik.pdf
- https://www.untis.at/manual/ulfach.htm
- https://help.untis.at/hc/de/articles/360012914560-Stammdaten-Fach
- https://help.untis.at/hc/de/articles/4405023012882-Klassenbuch-Stammdaten-Faecher
- https://platform.untis.at/HTML/WebHelp/de/untis/sd_weitere_stammd.htm
- https://help.untis.at/hc/de/articles/360013219860-Stammdaten-Schuelergruppe
- https://www.untis.at/manual/ahtageszeitraster.htm
- https://www.untis.at/manual/ahmittagspausen.htm
- https://help.untis.at/hc/de/articles/360009287119-Zeitraster (bloqueado; solo indexado)
- https://www.untis.at/manual/ur_doppelstunde_-_block.htm
- https://www.untis.at/manual/ur_unterricht_koppeln.htm
- https://www.untis.at/manual/ur_eingabe_eines_gekoppelten_unte.htm
- https://help.untis.at/hc/de/articles/360009297259-Bedingungen-fuer-Unterrichte
- https://help.untis.at/hc/de/articles/360009226080-Diagnose (bloqueado; solo indexado)
- https://www.untis.at/manual/diagnoseke.htm
- https://help.untis.at/hc/de/articles/360009112259-Rund-ums-Optimieren
- https://digbi.net/courses/untis-basics/lessons/untis-die-diagnose-vor-und-nach-der-stundenplanerstellung/
- https://www.untis.at/manual/sp_stundenplanformate.htm
- https://www.untis.at/manual/sp_stundenplaene_im_html-format.htm
- https://www.untis.at/manual/sp_druck_unterricht_und_stundenpl.htm
- https://www.untis.at/manual/druck_von_stundenplaenenke.htm
- https://www.untis.at/manual/pa_optimierung.htm
- https://www.untis.at/manual/pa_lehrer.htm
- https://platform.untis.at/HTML/WebHelp/de/untis/pa_lehrer.htm
- https://www.gpuntis.ch/downloads/untis-pausenaufsichten.pdf
- https://untis-baden-wuerttemberg.de/wp-content/uploads/2017/12/Pausenaufsichten.pdf
- https://www.untis.at/manual/vp_der_vertretungszaehler.htm (bloqueado; solo indexado)
- https://www.untis.at/manual/vp_einstellungen_zum_vertretungsz.htm
- https://www.untis.at/manual/vp_absenzen.htm
- https://www.untis.at/manual/vp_absenzeingabe.htm
- https://www.untis.at/manual/vp_absenzeingabe3.htm
- https://webhelp.untis.at/HTML/WebHelp/de/untis/vp_absenzeingabe3.htm
- https://www.untis.at/manual/vp_vertretungsvorschlag.htm
- https://www.untis.at/manual/vp_eigene_kriterien.htm
- https://www.untis.at/manual/vp_einstellungen_zum_vertretungsv.htm
- https://www.untis.at/manual/vp_vertretungslehrer_einsetzen.htm
- https://www.untis.at/manual/ulder_vertretungsvorschlag.htm
- https://www.untis.at/manual/vp_vertretungsart.htm
- https://www.untis.at/manual/vp_raumvertretung.htm
- https://www.gpuntis.ch/downloads/untis-vertretungsplanung.pdf
- http://www.pedav.de/dokumente/upload/vertretungs_anung.pdf
- https://www.untis.at/produkte/untis-das-grundpaket/kursplanung
- https://www.untis.at/manual/kp_sub_chapter_2_1.htm
- https://www.untis.at/manual/upallgemeines.htm
- https://www.untis.at/manual/upanrechnungen.htm
- https://www.untis.at/manual/updie_logik_des_unterrichtswerte.htm
- https://www.untis.at/de/niedersachsen/news/die-untis-wertrechnung
- https://www.untis.at/produkte/untis-das-grundpaket/mehrwochenstundenplan
- https://www.gpuntis.ch/downloads/untis-mehrwochenstundenplan.pdf
- https://www.untis.at/produkte/untis-das-grundpaket/multiuser
- https://webhelp.untis.at/HTML/WebHelp/de/untis/untis_content.htm
- https://www.untis.at/de/produkte/webuntis/schuljahreskalender
- https://help.untis.at/hc/de/articles/360009314259-Ferien-eingeben-Neues-Schuljahr
- https://www.untis.at/manual/eingabe_von_unterrichtsfreien_tagen.htm
- https://www.gpuntis.ch/downloads/untis-kalender.pdf
- https://www.gpuntis.ch/downloads/leitfaden.pdf
