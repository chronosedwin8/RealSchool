Aquí tienes un prompt mucho más completo. Está pensado para servir como la especificación maestra (Master Prompt) del proyecto y para que una IA actúe como arquitecto del sistema durante todo el desarrollo, no solo como generador de código.



Mi recomendación: guarda este documento como MASTER\_PROMPT\_SCHEDULING\_ENGINE.md. A partir de él podrás iniciar nuevas conversaciones sin perder el contexto arquitectónico.



\# MASTER PROMPT

\# Professional Academic Scheduling Engine

\# Version 1.0



Actúa como un Arquitecto Principal (Principal Software Architect) con más de 20 años de experiencia desarrollando motores de optimización para problemas NP-Hard utilizando Google OR-Tools, Constraint Programming (CP-SAT), Investigación Operativa (Operations Research), Inteligencia Artificial y algoritmos de optimización.



Tu función NO es escribir código rápidamente.



Tu función es diseñar la arquitectura de un producto comercial profesional que pueda evolucionar durante muchos años.



No quiero un proyecto de ejemplo.



No quiero un tutorial.



No quiero un CRUD.



No quiero un algoritmo básico.



Quiero diseñar un motor profesional comparable en arquitectura (NO en código) a productos como:



\- Untis

\- aSc Timetables

\- FET

\- TimeTabler

\- Prime Timetable



Todo el desarrollo debe priorizar:



\- escalabilidad

\- mantenibilidad

\- extensibilidad

\- rendimiento

\- claridad arquitectónica

\- separación de responsabilidades



Nunca sacrifiques arquitectura por rapidez.



\------------------------------------------------------------

OBJETIVO GENERAL

\------------------------------------------------------------



Construir un motor de generación automática de horarios escolares para instituciones educativas.



Debe ser capaz de generar horarios para:



\- colegios

\- universidades

\- institutos

\- centros técnicos

\- academias



Debe soportar cientos de restricciones configurables.



Debe poder crecer durante años sin necesidad de reescribir el núcleo.



\------------------------------------------------------------

FILOSOFÍA DEL PROYECTO

\------------------------------------------------------------



El motor NO depende de ninguna interfaz.



El motor NO depende de ninguna base de datos.



El motor NO depende de ningún framework web.



El motor NO conoce:



\- FastAPI

\- Django

\- Flask

\- Vue

\- React

\- Qt



El motor únicamente conoce objetos del dominio.



Debe ser una librería Python reutilizable.



Posteriormente podrá utilizarse desde:



\- Desktop

\- Web

\- API REST

\- CLI

\- Automatizaciones

\- Microservicios

\- IA



\------------------------------------------------------------

TECNOLOGÍA

\------------------------------------------------------------



Lenguaje



Python 3.13+



Motor de optimización



Google OR-Tools

CP-SAT



Tipado



Typing estricto



Persistencia



Ninguna.



El motor trabaja únicamente con objetos.



\------------------------------------------------------------

PRINCIPIOS

\------------------------------------------------------------



Aplicar siempre:



SOLID



Clean Architecture



DDD cuando tenga sentido



Repository Pattern



Strategy Pattern



Factory Pattern



Builder Pattern



Specification Pattern



Dependency Injection



Composition over Inheritance



Open Closed Principle



Single Responsibility Principle



No usar código duplicado.



Todo debe ser altamente desacoplado.



\------------------------------------------------------------

ESTRUCTURA DEL PROYECTO

\------------------------------------------------------------



core/



domain/



entities/



value\_objects/



aggregates/



constraints/



constraint\_groups/



strategies/



optimizer/



objective\_functions/



builders/



validators/



scoring/



events/



exceptions/



dto/



interfaces/



serialization/



configuration/



plugins/



tests/



benchmarks/



examples/



Cada carpeta debe tener una responsabilidad clara.



\------------------------------------------------------------

DOMINIO

\------------------------------------------------------------



Modelar correctamente como entidades de dominio:



Institución



Sede



Campus



Edificio



Piso



Aula



Laboratorio



Tipo de Aula



Capacidad del Aula



Equipamiento



Calendario



Período



Año Lectivo



Jornada



Marco Horario



Bloque Horario



Receso



Almuerzo



Docente



Disponibilidad Docente



Materia



Carga Académica



Asignación Docente



Curso



Grupo



Nivel



Sección



Ejemplos:



Kinder



Preescolar



Primaria



Secundaria



Bachillerato



Media



Estudiante



Horario



Clase



Evento



Restricción



Preferencia



Conflicto



Resultado



\------------------------------------------------------------

MULTI-INSTITUCIÓN

\------------------------------------------------------------



Debe soportar:



múltiples instituciones



múltiples sedes



múltiples edificios



múltiples jornadas



múltiples calendarios



múltiples marcos horarios



múltiples cursos



múltiples grupos



múltiples secciones



múltiples niveles



múltiples docentes



múltiples asignaciones



múltiples laboratorios



múltiples idiomas



\------------------------------------------------------------

RESTRICCIONES DURAS

\------------------------------------------------------------



Nunca pueden violarse.



Ejemplos:



Un docente no puede estar en dos lugares.



Un grupo no puede tener dos materias.



Un aula no puede tener dos clases.



Una materia debe cumplir exactamente su intensidad horaria.



Respetar disponibilidad docente.



Respetar disponibilidad de aulas.



Respetar disponibilidad institucional.



Los estudiantes nunca deben quedar con horas libres dentro del marco horario definido.



Los docentes deben tener obligatoriamente tiempo de almuerzo.



El almuerzo debe tener duración configurable.



Las materias dobles deben permanecer consecutivas.



Las materias triples deben permanecer consecutivas.



Máximo de horas diarias.



Máximo de horas consecutivas.



Máximo de carga semanal.



Compatibilidad docente-materia.



Compatibilidad materia-aula.



Compatibilidad aula-edificio.



Capacidad del aula.



Laboratorios exclusivos.



Eventos institucionales.



Festivos.



Bloqueos administrativos.



Restricciones legales.



\------------------------------------------------------------

RESTRICCIONES BLANDAS

\------------------------------------------------------------



Generan penalizaciones.



Preferencia mañana.



Preferencia tarde.



Evitar primeras horas.



Evitar últimas horas.



Evitar huecos docentes.



Balancear carga.



Balancear dificultad del estudiante.



Distribuir materias durante la semana.



Evitar demasiadas clases iguales el mismo día.



Mantener profesor en la misma aula.



Reducir desplazamientos.



Reducir cambios de edificio.



Reducir cambios de salón.



Agrupar materias relacionadas.



Optimizar utilización de aulas.



Preferencias institucionales.



\------------------------------------------------------------

SISTEMA DE PLUGINS

\------------------------------------------------------------



El motor NO debe conocer las restricciones.



Cada restricción debe implementarse como un plugin independiente.



Ejemplo:



constraints/



teacher/



teacher\_availability.py



teacher\_lunch.py



teacher\_max\_daily\_hours.py



teacher\_max\_weekly\_hours.py



teacher\_preferences.py



teacher\_no\_gaps.py



student/



student\_no\_gaps.py



student\_daily\_load.py



student\_distribution.py



room/



room\_capacity.py



room\_equipment.py



room\_building.py



subject/



double\_blocks.py



triple\_blocks.py



weekly\_distribution.py



morning\_only.py



institution/



holidays.py



events.py



Cada plugin implementa una interfaz común.



Ejemplo conceptual:



Constraint



↓



apply(model)



↓



agrega restricciones



↓



devuelve penalizaciones



El núcleo jamás debe modificarse para agregar nuevas reglas.



\------------------------------------------------------------

MOTOR DE OPTIMIZACIÓN

\------------------------------------------------------------



Debe utilizar exclusivamente:



Google OR-Tools



CP-SAT



Debe modelar correctamente:



Variables



Restricciones



Objetivos



Penalizaciones



Búsqueda



Optimización



Explicar siempre por qué se crea cada variable.



Explicar siempre por qué una restricción se modela de determinada manera.



\------------------------------------------------------------

FUNCIÓN OBJETIVO

\------------------------------------------------------------



Debe soportar múltiples objetivos.



Cada objetivo tendrá un peso configurable.



Ejemplo:



Minimizar huecos docentes.



Minimizar huecos estudiantes.



Minimizar desplazamientos.



Balancear cargas.



Reducir cambios de salón.



Maximizar preferencias.



Maximizar utilización de recursos.



Todo mediante una puntuación configurable.



\------------------------------------------------------------

ESCALABILIDAD FUTURA

\------------------------------------------------------------



El diseño debe permitir posteriormente:



Reoptimización parcial.



Congelar horarios.



Bloquear clases.



Resolver únicamente conflictos.



IA para sugerencias.



Explicación automática de conflictos.



Generación incremental.



Paralelización.



Optimización distribuida.



Versionado de horarios.



Comparación entre soluciones.



Historial.



Simulación.



Modo Sandbox.



\------------------------------------------------------------

SERIALIZACIÓN

\------------------------------------------------------------



El motor debe poder importar y exportar:



JSON



YAML



Archivo propio



Ejemplo



.proschedule



Toda la información del proyecto debe almacenarse allí.



\------------------------------------------------------------

RENDIMIENTO

\------------------------------------------------------------



El diseño debe considerar instituciones con:



500 docentes



300 aulas



1500 grupos



10 edificios



Miles de restricciones



Miles de variables



El código debe priorizar eficiencia.



\------------------------------------------------------------

CALIDAD

\------------------------------------------------------------



Cada módulo debe incluir:



Tests unitarios.



Tests de integración.



Benchmarks.



Validaciones.



No escribir código sin pruebas.



\------------------------------------------------------------

FORMA DE TRABAJO

\------------------------------------------------------------



Nunca generes todo el proyecto de una vez.



Siempre trabajarás por fases.



Cada fase debe terminar completamente antes de pasar a la siguiente.



FASE 1



Análisis del dominio.



FASE 2



Modelo del dominio.



FASE 3



Arquitectura.



FASE 4



Entidades.



FASE 5



Value Objects.



FASE 6



Interfaces.



FASE 7



Sistema de Plugins.



FASE 8



Modelo matemático.



FASE 9



Variables CP-SAT.



FASE 10



Restricciones.



FASE 11



Objetivos.



FASE 12



Motor.



FASE 13



Optimizador.



FASE 14



Scoring.



FASE 15



Serialización.



FASE 16



Benchmarks.



FASE 17



API Pública.



No avanzar nunca sin justificar completamente el diseño anterior.



\------------------------------------------------------------

REGLAS IMPORTANTES

\------------------------------------------------------------



Nunca escribir código sin explicar primero la arquitectura.



Nunca utilizar variables globales.



Nunca acoplar el dominio con OR-Tools.



El dominio no debe conocer CP-SAT.



El optimizador será una capa independiente.



Cada restricción debe poder activarse o desactivarse dinámicamente.



Cada restricción debe ser fácilmente testeable.



Cada objetivo debe ser configurable.



Cada algoritmo debe poder reemplazarse.



Todo el proyecto debe estar preparado para que en el futuro pueda sustituirse OR-Tools por otro solver sin modificar el dominio.



Cuando propongas una solución, justifica siempre:



\- por qué

\- ventajas

\- desventajas

\- impacto en rendimiento

\- impacto en mantenibilidad

\- impacto en escalabilidad



Si detectas una decisión arquitectónica mejor que la planteada inicialmente, propón la mejora antes de escribir código y explica sus implicaciones.



Actúa siempre como el arquitecto principal del proyecto y prioriza decisiones que permitan que este motor evolucione durante los próximos 10 años.

Una mejora arquitectónica que añadiría



Hay una mejora que considero fundamental y que no aparece en Untis de forma explícita: separar completamente el modelo académico del solver.



La arquitectura quedaría así:



&#x20;               Academic Domain

&#x20;                      │

&#x20;                      ▼

&#x20;            Scheduling Domain Model

&#x20;                      │

&#x20;                      ▼

&#x20;             Constraint Translator

&#x20;                      │

&#x20;                      ▼

&#x20;             OR-Tools (CP-SAT)

&#x20;                      │

&#x20;                      ▼

&#x20;               Solution Builder

&#x20;                      │

&#x20;                      ▼

&#x20;               Academic Schedule



Es decir:



El dominio académico nunca conoce OR-Tools.

OR-Tools nunca conoce qué es un docente o una materia.

Existe una capa intermedia (Constraint Translator) que transforma el modelo de dominio en variables y restricciones CP-SAT, y otra (Solution Builder) que reconstruye el horario desde la solución del solver.



Esta separación hace que, si en cinco años decides reemplazar OR-Tools por Gurobi, OptaPlanner o cualquier otro solver, el dominio permanezca intacto y solo debas sustituir las capas de traducción y resolución. Es una inversión arquitectónica que reduce significativamente el acoplamiento y aumenta la vida útil del proyecto.



entonces dame el prompt con la mejora arquitectónica que sugieres



La mejora que propongo no es un detalle menor; es la decisión que probablemente más influirá en la calidad del proyecto. Si fuera el arquitecto principal de un software destinado a competir con Untis durante los próximos diez años, esa sería la arquitectura desde el primer día.



La diferencia es que ya no construyes un "motor basado en OR-Tools", sino una plataforma de optimización donde OR-Tools es solo un componente reemplazable.



Además, haría una mejora adicional respecto al prompt anterior:



Event Sourcing ligero para registrar decisiones importantes del motor.

Sistema de capacidades (Capabilities) para que distintas ediciones del software activen o desactiven funciones sin modificar el código.

Motor de reglas (Rule Engine) independiente del solver.

Constraint Translator (Dominio → Solver).

Solution Builder (Solver → Dominio).

Plugin SDK para que terceros desarrollen restricciones.

Sistema de métricas y benchmarking para comparar la calidad de diferentes algoritmos.



Ese sería el tipo de arquitectura que esperaría encontrar en un producto comercial moderno.



Sin embargo, el prompt ya supera ampliamente el límite práctico de longitud que una IA puede manejar cómodamente en una sola conversación. Si sigo añadiendo mejoras, terminará siendo inmanejable y muchas partes dejarán de influir en las respuestas.



Mi recomendación profesional



En lugar de un único prompt gigantesco, construiría una especificación técnica completa de unas 200–300 páginas en Markdown, que sirva como la documentación oficial del proyecto. Por ejemplo:



SchedulingEngine/



01-Visión-General.md



02-Objetivos.md



03-Requisitos.md



04-Dominio.md



05-Modelo-de-Datos.md



06-Arquitectura.md



07-Patrones.md



08-Core.md



09-Domain.md



10-Rule-Engine.md



11-Plugin-SDK.md



12-Constraint-Translator.md



13-Optimization.md



14-Objective-Functions.md



15-Scoring.md



16-Solution-Builder.md



17-Serialization.md



18-Desktop.md



19-Web.md



20-API.md



21-Testing.md



22-Benchmarks.md



23-Roadmap.md



24-ADR/



Y dentro de ADR (Architecture Decision Records):



ADR-001

¿Por qué Python?



ADR-002

¿Por qué OR-Tools?



ADR-003

¿Por qué Plugin Architecture?



ADR-004

¿Por qué Clean Architecture?



ADR-005

¿Por qué Domain Driven Design?



ADR-006

¿Por qué Constraint Translator?



ADR-007

¿Por qué Solution Builder?



Esto es exactamente el enfoque que utilizan muchos proyectos de software complejos: la arquitectura vive en documentos versionados, mientras que los prompts sirven para desarrollar una parte concreta del sistema.



Lo que haría si este fuera mi proyecto



Conociendo el alcance que buscas, no empezaría escribiendo código.



Primero diseñaría el producto como si fuera un competidor serio de Untis, y documentaría toda la arquitectura antes de implementar el primer módulo.



Mi propuesta sería crear una especificación técnica completa en Markdown, organizada por módulos y con diagramas, patrones de diseño, modelos del dominio y decisiones arquitectónicas. Esa documentación se convertiría en la "fuente de verdad" del proyecto y serviría tanto para el desarrollo manual como para guiar a una IA en cada fase.



Creo que ese enfoque aumentaría mucho la calidad del resultado final y reduciría el riesgo de tener que rehacer partes importantes del motor cuando el proyecto crezca. De hecho, es el mismo tipo de documentación que suelen mantener los equipos que desarrollan productos complejos y de larga vida útil.



listo dame tu propuesta segun lo que me indicas



Creo que este proyecto merece tratarse como un producto comercial, no como un desarrollo personal.



Por lo que hemos hablado en conversaciones anteriores, veo una oportunidad real. Ya conoces muy bien Untis desde el punto de vista del usuario, conoces las necesidades de un colegio, has trabajado con WebUntis y además tienes experiencia en desarrollo. Esa combinación es poco común.



Mi propuesta



Yo no haría un "clon de Untis".



Haría una plataforma llamada, por ejemplo, OpenTimetable Engine (OTE) (el nombre es solo provisional), cuyo objetivo sea convertirse en un motor de horarios genérico.



Es decir, que el motor no sepa absolutamente nada de colegios.



Para el motor solamente existen recursos, actividades, restricciones y tiempos.



Eso permite reutilizarlo para:



colegios

universidades

hospitales

horarios laborales

centros deportivos

reservas de salas

fábricas



Luego construiríamos un módulo académico encima.



La arquitectura

&#x20;                   Desktop



&#x20;                       │



&#x20;                       ▼



&#x20;            Academic Application



&#x20;                       │



&#x20;                       ▼



&#x20;              Academic Domain



&#x20;                       │



&#x20;                       ▼



&#x20;            Scheduling Domain



&#x20;                       │



&#x20;                       ▼



&#x20;                Rule Engine



&#x20;                       │



&#x20;                       ▼



&#x20;           Constraint Translator



&#x20;                       │



&#x20;                       ▼



&#x20;           Solver Abstraction Layer



&#x20;               │             │



&#x20;        OR-Tools         Futuro Gurobi



&#x20;               │



&#x20;               ▼



&#x20;         Solution Builder



&#x20;               │



&#x20;               ▼



&#x20;          Validation Engine



&#x20;               │



&#x20;               ▼



&#x20;         Academic Schedule



Observa que OR-Tools está encerrado en una capa.



Eso significa que si algún día aparece un solver mejor, el resto del sistema no cambia.



División del proyecto



Yo dividiría el proyecto en nueve grandes módulos.



Módulo 1



Core Framework



Aquí viven:



Dependency Injection

Logging

Eventos

Configuración

Plugins

Errores

Utilidades



Este módulo nunca conocerá qué es un docente.



Módulo 2



Optimization Engine



Aquí vive únicamente:



Solver

Variables

Restricciones matemáticas

Función objetivo



No sabe qué es un curso.



Módulo 3



Rule Engine



Este módulo administra reglas.



Ejemplo:



TeacherLunchRule



↓



TeacherAvailabilityRule



↓



StudentNoGapRule



↓



DoubleLessonRule



↓



HolidayRule



Cada regla es independiente.



Módulo 4



Academic Domain



Aquí aparecen por primera vez:



Docente



Materia



Curso



Grupo



Sección



Edificio



Salón



Carga Académica



Módulo 5



Translator



Este será posiblemente el módulo más importante.



Transforma



Profesor Juan



↓



Variable x(14582)



Transforma



Grupo 7A



↓



Variable y(84211)



Transforma



Materia Matemáticas



↓



Restricción CP-SAT



Aquí ocurre toda la magia.



Módulo 6



Solution Builder



Cuando OR-Tools devuelve:



x14582 = 1



x14583 = 0



x14584 = 1



Este módulo reconstruye:



Lunes



Hora 2



Profesor Juan



Matemáticas



7A



Salón 205

Módulo 7



Validation Engine



Después de obtener una solución.



Se vuelve a validar.



Ejemplo:



Profesor duplicado



❌

Hueco estudiante



❌

Laboratorio ocupado



❌



Todo debe verificarse otra vez.



Nunca confiar únicamente en el solver.



Módulo 8



Metrics Engine



Esto no lo tiene Untis de forma tan abierta.



Calculará indicadores como:



Calidad



98.2%

Huecos docentes



12

Huecos estudiantes



0

Cambios de edificio



14

Carga equilibrada



95%



Así podrás comparar dos horarios objetivamente.



Módulo 9



Persistence



Aquí recién aparecen



SQLite



PostgreSQL



JSON



XML



Archivos



Pero el motor nunca depende de ellos.



Ahora viene la mejor idea



Yo construiría un SDK.



Es decir.



Cualquier persona podría escribir una regla.



Ejemplo.



TeacherLunchRule



Solo implementa:



class TeacherLunchRule(Rule):



&#x20;   def apply(self, context):

&#x20;       ...



Y automáticamente el motor la reconoce.



Eso significa que nunca más tendrás que modificar el núcleo.



Después construiría un Marketplace



Imagina:



Plugin



Colegios Alemania



Otro:



Plugin



Ministerio Colombia



Otro:



Plugin



IB Schools



Otro



Plugin



Universidades



Todos usando el mismo motor.



Otro cambio enorme



No utilizaría únicamente restricciones.



Crearía dos motores.



Rule Engine



y



Scoring Engine



Porque muchas reglas realmente son preferencias.



Ejemplo



Profesor prefiere mañana



Eso NO debería ser una restricción.



Debe ser una preferencia.



Entonces



Rule Engine



dice



Es válido



Scoring Engine



dice



98 puntos



Otro horario



95 puntos



El mejor gana.



Roadmap



Yo haría algo así.



FASE 0



Arquitectura

FASE 1



Modelo del dominio

FASE 2



Core Framework

FASE 3



Plugin SDK

FASE 4



Rule Engine

FASE 5



Translator

FASE 6



OR-Tools

FASE 7



Solution Builder

FASE 8



Validation

FASE 9



Persistence

FASE 10



Desktop

FASE 11



API

FASE 12



Web

Y aquí está la decisión que considero más importante de todo el proyecto



Yo no haría primero el programa.



Haría primero la especificación técnica.



Mi propuesta concreta



Antes de escribir una sola línea de código, desarrollaría una documentación técnica equivalente a la de un producto comercial. La organizaría aproximadamente así:



Volumen I – Visión del Producto: objetivos, alcance, casos de uso, actores, requisitos funcionales y no funcionales.

Volumen II – Arquitectura: principios de diseño, diagramas, módulos, patrones, ADR (Architecture Decision Records) y modelo de capas.

Volumen III – Dominio Académico: entidades, agregados, reglas de negocio, relaciones y glosario.

Volumen IV – Motor de Optimización: modelo matemático, traductor de restricciones, abstracción del solver, función objetivo y estrategia de búsqueda.

Volumen V – SDK de Plugins: cómo desarrollar nuevas restricciones, nuevas funciones de puntuación y nuevos conectores.

Volumen VI – APIs e Integraciones: formato de proyectos, serialización, API pública y protocolos de intercambio.

Volumen VII – Pruebas y Rendimiento: estrategia de pruebas, benchmarking, conjuntos de datos y métricas de calidad.



En total, esta documentación rondaría las 250 a 400 páginas en Markdown. A partir de ahí, cada módulo se implementaría siguiendo esa especificación.



Mi experiencia es que este enfoque reduce enormemente la probabilidad de rediseños costosos cuando el sistema crece. En un proyecto de esta complejidad, la arquitectura es el activo más valioso; el código viene después.







