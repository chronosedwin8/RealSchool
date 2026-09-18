# Paridad de flujo con Untis: 30 tareas del planificador

Criterio de aceptación de R5 (`REFACTOR_UNTIS_MAESTRO.md`, sección 10): un
planificador de Untis debe poder hacer en RealSchool las tareas típicas de su
trabajo, con el mismo flujo. Cada tarea indica dónde se hace y qué prueba
automática la cubre; la columna **Manual** se marca al comprobarla a mano en la
aplicación con los datos del colegio.

Datos de referencia: export real 2025-2026 (seudonimizado en
`tests/fixtures/untis_anon.xml`; 66 clases, 116 profesores, 722 lecciones).

| # | Tarea | Dónde | Prueba automática | Manual |
| --- | --- | --- | --- | --- |
| 1 | Abrir el XML exportado de Untis | Inicio → Abrir | `test_untis_facade::test_abrir_xml_real_deduce_recreos_y_activa_el_horario` | ☐ |
| 2 | Importar archivos GPU de otra instalación | CLI `convert <carpeta> x.rsp` / Abrir carpeta | `test_cli_untis::test_convert_rsp_a_gpu_y_vuelta` | ☐ |
| 3 | Guardar el proyecto y reabrirlo sin pérdidas | Inicio → Guardar (`.rsp`) | `test_untis_facade::test_guardar_y_reabrir_rsp`, `test_interop_rsp` | ☐ |
| 4 | Revisar y corregir la rejilla de tiempo (horas, recreos, tarde) | Datos maestros → Rejillas de tiempo | `test_desktop_data_windows` (rejillas) | ☐ |
| 5 | Dar de alta una clase, un profesor, un aula, una materia | Datos maestros → Clases / Profesores / Aulas / Materias | `test_untis_facade::test_alta_y_baja_de_entidades`, `test_desktop_data_windows` | ☐ |
| 6 | Editar en la cuadrícula con validación inmediata (celda roja) | Cuadrícula de datos maestros | `test_untis_facade::test_edicion_invalida_devuelve_fallo_sin_cambiar_nada`, `test_desktop_data_windows` | ☐ |
| 7 | Mostrar/ocultar y reordenar columnas; que se recuerde | Cabecera de la cuadrícula (menú contextual) | `test_desktop_data_windows` (persistencia de columnas) | ☐ |
| 8 | Fijar mín-máx de períodos por día y huecos de un profesor | Profesores → columnas mín-máx | `test_untis_facade::test_tabla_de_datos_maestros_y_edicion`, `test_evaluation` | ☐ |
| 9 | Encadenar aulas alternativas y capacidad | Aulas | `test_evaluation::test_aulas_cadena_capacidad_y_exigida`, `test_bridge::test_pool_de_aulas_sigue_la_cadena_de_alternativas` | ☐ |
| 10 | Marcar materias principales y grupos de materias | Materias | `test_evaluation::test_materias_principales`, `test_grupo_de_materias_seguidas` | ☐ |
| 11 | Crear una lección y asignar profesor, clases y períodos | Lecciones → Nueva lección | `test_untis_facade::test_lecciones_alta_edicion_y_acople` | ☐ |
| 12 | Acoplar y desacoplar líneas (Kopplung) | Lecciones → Acoplar / Desacoplar | `test_untis_facade::test_lecciones_alta_edicion_y_acople`, `test_desktop_data_windows` | ☐ |
| 13 | Pedir períodos dobles y bloques | Lecciones → Dobles / Bloque | `test_evaluation::test_dobles`, `test_polish::test_pulido_logra_el_doble_pedido` | ☐ |
| 14 | Ver la carga de una clase o profesor frente a su capacidad | Lecciones → barra de suma | `test_untis_facade::test_resumen_de_carga`, `test_desktop_data_windows` | ☐ |
| 15 | Filtrar lecciones al elegir una clase en Datos maestros | Selección sincronizada | `test_desktop_shell::test_puente_seleccion_sincronizada`, `test_desktop_data_windows` | ☐ |
| 16 | Poner deseos −3…+3 por celda y por día completo | Datos maestros → Deseos de tiempo | `test_untis_facade::test_deseos_de_tiempo`, `test_desktop_data_windows` | ☐ |
| 17 | Pedir "2 tardes libres" (deseo no especificado) | Deseos de tiempo → no especificados | `test_untis_facade::test_deseos_no_especificados`, `test_evaluation::test_deseos_blandos_y_no_especificados` | ☐ |
| 18 | Ajustar ponderaciones 0–5 con ayuda por criterio | Módulos → Ponderación | `test_untis_facade::test_ponderacion_nueve_pestanas`, `test_desktop_data_windows` | ☐ |
| 19 | Revisar el Diagnóstico de datos antes de optimizar | Panel Diagnóstico (Datos de entrada) | `test_untis_facade::test_evaluacion_y_diagnostico_real`, `test_desktop_planning_windows` | ☐ |
| 20 | Correr la estrategia A para detectar errores | Horarios → Optimización → A | `test_untis_facade::test_optimizar_estrategia_a_sintetica`, `test_heuristic_real` | ☐ |
| 21 | Correr la estrategia B y detenerla a mitad | Optimización → B → Detener | `test_heuristic` (should_stop), `test_desktop_planning_windows` | ☐ |
| 22 | Leer el número de evaluación y su desglose | Horarios → Evaluación / Ponderación → Análisis | `test_evaluation`, `test_desktop_planning_windows` | ☐ |
| 23 | Comparar dos horarios generados y activar el mejor | Evaluación → lista de horarios | `test_desktop_planning_windows` | ☐ |
| 24 | Saltar del Diagnóstico a la lección en conflicto | Doble clic en el Diagnóstico | `test_desktop_planning_windows` | ☐ |
| 25 | Mover una clase a mano viendo destinos y coste | Diálogo de planificación (arrastrar) | `test_untis_facade::test_planificacion_mover_desprogramar_fijar`, `test_desktop_planning_windows` | ☐ |
| 26 | Desprogramar (F7), fijar e intercambiar sesiones | Diálogo de planificación (menú contextual) | `test_desktop_planning_windows` | ☐ |
| 27 | Reparar un choque con cambio mínimo | Optimización → Reparar | `test_repair::test_real_repara_los_siete_choques_de_untis` | ☐ |
| 28 | Deshacer cualquier cambio | Inicio → Deshacer | `test_desktop_shell::test_puente_edita_avisa_y_deshace` | ☐ |
| 29 | Ver horarios por clase/profesor/aula con formatos e imprimir o sacar PDF/HTML | Horarios | `test_desktop_planning_windows` (formatos, HTML, PDF) | ☐ |
| 30 | Exportar `GPU001.TXT` para MiUntisWeb y XML para Untis | Horarios → Exportar / CLI `convert` | `test_untis_facade::test_exportar_gpu_con_nombres_cortos`, `test_cli_untis` | ☐ |

## Pendiente de comprobación manual

- Que **MiUntisWeb** abra el `GPU001.TXT` exportado sin cambios (el formato
  replica el de Untis 2022 con nombres cortos, pero no se ha probado contra el
  visor real).
- Que **Untis 2022** importe el XML y los GPU exportados.
- La tarea 29 en papel (impresora real).
