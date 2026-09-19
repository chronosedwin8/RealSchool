# Preguntas frecuentes

Las dudas que salen siempre, con la respuesta corta y el enlace a la página que lo explica
despacio.

## Sobre generar el horario

### El generador pone clase a horas en que ya no hay servicio

Te falta el **marco horario**. El programa no sabe a qué hora cierra tu colegio: hay que
decírselo. Abre [Deseos de tiempo](04-deseos-y-marco-horario.md), indica en **Hay clase de la
hora:** la primera y la última hora de la jornada, elige en **Aplicar a:** la opción "todos los
de su rejilla" y pulsa **Aplicar marco horario**. Las horas de fuera quedan cerradas con -3 y
el generador no las usa nunca.

![Marco horario en Deseos de tiempo](img/requests.png)

### Quedan horas sin colocar

No es mala suerte: es que no caben. Abre el
[Diagnóstico](08-diagnostico-y-evaluacion.md) y mira los mensajes en rojo. Las causas
habituales son tres:

- un profesor o una clase tiene más horas de lección que huecos libres en su rejilla;
- hay demasiados **-3** en los deseos y ya no queda sitio;
- faltan aulas de un tipo que varias lecciones piden a la vez.

Si el diagnóstico está limpio y aun así quedan horas sueltas, colócalas tú en el
[Diálogo de planificación](09-planificacion-manual.md): las celdas verdes son destinos
posibles.

### ¿Qué es el número de evaluación?

La nota del horario, y mide **lo malo**: cuanto más bajo, mejor. Las horas sin colocar y los
choques pesan muchísimo, así que un horario con choques siempre tendrá un número enorme. Sirve
sobre todo para comparar dos horarios del mismo colegio, no para compararse con otro centro.
Ver [Diagnóstico y evaluación](08-diagnostico-y-evaluacion.md).

## Sobre Untis

### ¿Puedo usar mis datos de Untis?

Sí. Desde la pestaña Inicio, **Importar** (Ctrl+I) tiene dos opciones: **Archivo XML de
Untis...** y **Carpeta con archivos GPU...**. También puedes abrir el XML directamente con
**Abrir**. Entran datos maestros, lecciones, deseos y horarios. Ver
[Importar y exportar](13-importar-y-exportar.md).

### ¿Se puede volver a Untis?

Sí. Abre la ventana **Horarios**, despliega **Imprimir / Exportar** y elige **Exportar XML
(Untis)...** para llevarte el proyecto entero, o **Exportar GPU (MiUntisWeb)...** para los
archivos del horario activo. La ida y la vuelta no pierden datos maestros, lecciones ni
horarios. Lo que es propio de RealSchool (las zonas de guardia y el parte de sustituciones)
vive solo en el archivo del proyecto.

### ¿Puedo trabajar sin Untis, desde cero?

Sí, y es el camino normal. En la página de Inicio, pulsa **Crear un colegio nuevo**: un
asistente te pide el nombre, los días y las horas de clase, y a partir de ahí no necesitas
ningún otro programa. También puedes pulsar **Abrir un ejemplo** para trastear con un colegio
ya preparado antes de meter tus datos. Ver [Primeros pasos](01-primeros-pasos.md).

## Sobre los datos

### ¿Dónde se guardan los datos?

En un único archivo con extensión **.rsp**, donde tú lo guardes. Dentro va todo: colegio,
rejillas, datos maestros, lecciones, deseos, ponderación, todos los horarios generados, las
zonas y turnos de guardia, las ausencias y las sustituciones. Copiar ese archivo es copiar el
colegio entero.

No hay guardado automático: pulsa **Ctrl+S** a menudo. Cuando hay cambios sin guardar, el
título de la ventana lleva un asterisco y abajo a la derecha pone "Sin guardar".

### ¿Puedo cargar las listas desde Excel?

Sí, de dos maneras. En cualquier tabla de [Datos maestros](02-datos-maestros.md), copia el
bloque en la hoja de cálculo y pulsa **Ctrl+V**: entra entero y en un solo paso de deshacer.
O usa el botón **Importar CSV**, que antes de nada te enseña qué va a pasar. Para el camino de
vuelta está **Exportar CSV**.

### ¿Se puede deshacer?

Sí, prácticamente todo: **Ctrl+Z** deshace y **Ctrl+Y** rehace. Incluye la carga masiva de un
CSV, el reparto de guardias y las decisiones de sustitución. Pasa el ratón por el botón
**Deshacer** y verás qué se va a deshacer exactamente antes de pulsarlo. No se deshacen
guardar, exportar ni imprimir, porque no tocan el proyecto.

## Sobre la jornada, las guardias y el día a día

### ¿Puedo tener jornadas distintas por sección?

Sí. Crea una **rejilla de tiempo** por cada jornada (por ejemplo "Primaria" y "Bachillerato"),
cada una con sus días, sus horas y sus recreos, y asigna a cada clase la suya en la ventana
Clases. Todo lo demás (deseos, marco horario, guardias) se aplica sobre la rejilla que le
corresponde. Ver [Rejillas de tiempo](03-rejillas-de-tiempo.md).

### ¿El programa reparte las guardias de recreo solo?

Sí. Crea las zonas que hay que vigilar, pulsa **Generar turnos** y después **Repartir
guardias**. El reparto solo propone a quien da clase justo antes o justo después del recreo,
no pone a nadie en dos sitios a la vez, respeta el tope de minutos semanales de cada profesor y
equilibra la carga. Lo que pongas tú a mano queda con chincheta y el reparto no lo toca. Ver
[Guardias de recreo](11-guardias-de-recreo.md).

### ¿Por qué un profesor sale en rojo en el resumen de guardias?

Porque se ha pasado de su máximo semanal, la columna **Guardias: minutos/semana máx** de
Profesores. El reparto automático nunca se lo salta; si está en rojo es que alguien le puso un
turno a mano. Súbele el máximo o quítale un turno.

### ¿Qué pasa si falta un profesor?

Abre **Sustituciones**, elige el día y pulsa **Añadir** para registrar la ausencia (también
puede faltar una clase entera o un aula). El programa te lista las clases afectadas y, con
**Proponer sustituto**, los profesores que pueden cubrirlas ordenados del mejor al peor. Si no
hay nadie, puedes **Suprimir** la clase o **Cambiar aula**. Ver
[Sustituciones](12-sustituciones.md).

### ¿Cómo evito que a alguien le toque siempre sustituir?

Mira la columna **Contadores** de la ventana Sustituciones: cuenta cuántas lleva cada uno, y el
programa ya prefiere a quien menos acumula. Si alguien no debe sustituir nunca, ponle un **9**
en la columna **Reserva para sustituir (0-9)** de Profesores: no se le propondrá jamás.

## Sobre imprimir y el programa

### ¿Puedo imprimir los horarios?

Sí. En la ventana **Horarios** eliges el tipo (clase, profesor, aula o materia) y la entidad, y
el botón **Imprimir / Exportar** ofrece: **Imprimir...**, **PDF del horario...**, **HTML del
horario...**, **Exportar todos (HTML, uno por entidad)...** y **Exportar todos (un PDF)...**.
Las cabeceras y el pie de página se escriben en Datos del colegio. Ver
[Horarios, impresión y PDF](10-horarios-impresion-y-pdf.md).

![Ventana Horarios](img/timetables.png)

### ¿En qué idiomas está?

En **español** y **alemán**. Se cambia en la pestaña **Vista**, grupo **Idioma**, y el cambio
es inmediato: menús, ventanas, botones y la ayuda F1. No hace falta reiniciar.

### ¿Dónde está la ayuda del programa?

Pulsa **F1** en cualquier ventana y sale su ficha: para qué sirve, los pasos y unos consejos.
**Shift+F1** abre la guía rápida con el flujo completo. Y en la página de Inicio, la lista
**Primeros pasos** se va marcando sola conforme completas cada parte.

---

¿No está tu duda? Mira el índice del [manual](Home.md) o prueba con
[Atajos y trucos](14-atajos-y-trucos.md).
