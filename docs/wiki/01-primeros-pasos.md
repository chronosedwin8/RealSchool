# Primeros pasos

RealSchool arma el horario de un colegio: se le dice cuándo hay clase, quién enseña qué a quién,
y el programa coloca todas las horas de la semana.

## Qué es RealSchool

Es un programa de escritorio. Se abre desde su icono, como cualquier otro programa, y trabaja
siempre sobre un proyecto: un archivo con extensión `.rsp` que guarda todo el colegio (la jornada,
las clases, los profesores, las lecciones y los horarios generados).

No hace falta estar conectado a internet y no hay que instalar nada en cada computador del
colegio: el proyecto es un solo archivo que se puede copiar o guardar en una carpeta compartida.

## La pantalla de inicio

Al abrir el programa aparece la pantalla de inicio. También se vuelve a ella en cualquier momento
con Ctrl+0.

![Pantalla de inicio](img/start.png)

Arriba hay cuatro tarjetas:

- **Crear un colegio nuevo**: abre un asistente que pide el nombre, los días y las horas de clase.
- **Abrir proyecto**: continúa con un proyecto guardado de RealSchool (.rsp).
- **Importar de Untis**: despliega dos opciones, "Archivo XML de Untis..." y "Carpeta con
  archivos GPU...".
- **Abrir un ejemplo**: abre un colegio real ya preparado, con su horario generado. Sirve para
  mirar cómo queda todo antes de empezar con el colegio propio.

A la derecha, la etiqueta azul resume el proyecto abierto: el nombre del colegio y cuántas clases,
profesores y lecciones tiene. Debajo, a la derecha, están los **Proyectos recientes**: los últimos
que se abrieron o guardaron, para volver a ellos con un clic.

## Crear un colegio nuevo con el asistente

1. Pulsa **Crear un colegio nuevo**.
2. En "Tu colegio" escribe el nombre del colegio y las fechas de inicio y fin del curso.
3. En "La semana" marca los días en que hay clase. Lo normal es de lunes a viernes.
4. En "La jornada" indica a qué hora empieza la primera clase, cuánto dura cada período, el
   cambio de clase y cuántos períodos hay al día. Con **Añadir recreo** se indica después de qué
   período va cada recreo y cuántos minutos dura. Abajo se ve la vista previa de las horas.
5. En "Clases, profesores y materias" puedes escribir los nombres cortos separados por comas o uno
   por línea. Es opcional: se pueden añadir después.
6. En "Todo listo" revisa el resumen y pulsa **Finalizar**.

Los nombres cortos son los que salen impresos en los horarios: usa pocas letras (6A, ANA, MAT).
Los nombres completos se rellenan luego en [Datos maestros](02-datos-maestros.md).

## La lista "Primeros pasos"

Debajo de las tarjetas está la lista de los ocho pasos que llevan del proyecto vacío al horario
impreso. Cada paso dice en qué va ("66 clases, 116 profesores, 95 aulas, 279 materias") y trae un
botón que abre la ventana donde se hace.

| Paso | Qué se hace |
| --- | --- |
| 1. Rejilla de tiempo | Días lectivos, horas de cada período y recreos |
| 2. Datos maestros | Clases, profesores, aulas y materias |
| 3. Lecciones | Qué profesor da qué materia a qué clase y cuántas horas |
| 4. Deseos de tiempo (opcional) | Horas en las que alguien no puede tener clase |
| 5. Ponderación (opcional) | Qué criterios de calidad pesan más |
| 6. Generar el horario | Optimización: pulsar Iniciar |
| 7. Revisar y retocar | Evaluación, Diagnóstico y Diálogo de planificación |
| 8. Imprimir y exportar | Horarios en papel, PDF o HTML |

Cada paso lleva una etiqueta con su estado: **Hecho** (verde), **Pendiente**, **Revisar** (algo
quedó con problemas), **Opcional** o **Disponible**. El primer paso sin terminar se resalta en
azul con la marca "siguiente paso", y ese mismo texto aparece arriba, bajo el título.

## En qué orden conviene trabajar

El orden de la lista no es un capricho: cada paso necesita el anterior.

1. Primero el tiempo: [las rejillas](03-rejillas-de-tiempo.md). Sin horas no hay dónde colocar
   nada.
2. Después los departamentos, si se van a usar, y el resto de los
   [datos maestros](02-datos-maestros.md).
3. Luego las lecciones.
4. Los [deseos de tiempo](04-deseos-y-marco-horario.md) y la ponderación, al final y solo si hacen
   falta.
5. Por último, generar, revisar e imprimir.

Si los datos vienen de Untis o de una hoja de cálculo, mira
[Importar y exportar](13-importar-y-exportar.md) antes de teclear nada.

## Guardar el proyecto

- **Ctrl+S** (botón **Guardar**) escribe el proyecto en su archivo .rsp.
- **Guardar como** lo guarda con otro nombre o en otra carpeta.
- Mientras haya cambios sin guardar, la barra de estado muestra "Sin guardar".
- Si intentas cerrar o abrir otro proyecto con cambios pendientes, el programa pregunta
  "Hay cambios sin guardar. ¿Descartarlos?".

Guarda a menudo. Generar un horario grande puede tardar y no conviene perder el trabajo previo.

## Deshacer y rehacer

Todos los cambios se pueden deshacer con **Ctrl+Z**, incluidos los grandes: importar un CSV,
pegar un bloque desde Excel o borrar una rejilla entran como un solo paso de deshacer.

El botón **Deshacer** de la cinta dice qué se va a deshacer ("Deshacer: Importar 66 clases"), así
que se sabe de antemano qué se pierde. **Ctrl+Y** vuelve a aplicar lo deshecho.

## Ayuda dentro del programa

Pulsa **F1** en cualquier ventana: se abre la ficha de esa ventana, con para qué sirve, los pasos
y algunos consejos. En la cinta, **Guía rápida** muestra el flujo completo.

## Errores frecuentes

- **"Abrir un ejemplo" no aparece.** La tarjeta solo se ve si el colegio de ejemplo está
  instalado junto al programa. No es un fallo: empieza con "Crear un colegio nuevo".
- **La lista de pasos sigue en "Pendiente" aunque ya metí los datos.** Los pasos se marcan solos
  al completarse. Datos maestros pide al menos una clase, un profesor y una materia; con las aulas
  vacías el paso ya cuenta como hecho, porque las aulas son opcionales.
- **Cerré el programa y perdí lo último que hice.** El proyecto solo se guarda cuando se pulsa
  Ctrl+S. Si la barra de estado dice "Sin guardar", hay cambios sin escribir en el archivo.
