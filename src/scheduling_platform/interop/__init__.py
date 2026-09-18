"""Interoperabilidad: lectura y escritura de formatos externos y del proyecto.

Un solo modelo (`untis_model`), varios serializadores. Ningún formato pasa por
otro: `xml`, `gpu` y `rsp` leen y escriben `UntisProject` directamente
(`REFACTOR_UNTIS_MAESTRO.md`, sección 9).
"""
