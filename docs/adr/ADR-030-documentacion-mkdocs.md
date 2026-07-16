# ADR-030: Documentación del SDK con MkDocs Material + mkdocstrings

**Fecha:** 2026-07-16 · **Estado:** Aceptado

## Contexto
Las Fases 1–3 dejaron un motor, un CLI y un formato `.bjs` operativos. Para que la
plataforma sea **extensible por terceros** hace falta documentar el modelo mental,
los contratos y los puntos de extensión, con una doc que **no se desincronice** del
código y sea **100 % offline**.

## Decisión

### 1. Docs-as-Code: MkDocs Material + mkdocstrings + Mermaid
- **MkDocs Material** para el sitio (tema claro/oscuro, navegación, búsqueda).
- **mkdocstrings** genera la referencia de API **desde los docstrings** del código
  (nunca queda desactualizada).
- **Mermaid** para los diagramas de flujo.
- Dependencias aisladas en un extra `docs` de `pyproject` (no engordan el motor).

### 2. Offline real
`use_directory_urls: false` y `theme.font: false` → el sitio abre con
`file://site/index.html` **sin servidor ni CDN**; la búsqueda va empaquetada.
Mermaid se **vendoriza localmente** (`docs/assets/js/mermaid.min.js`) con un init
que re-renderiza los diagramas al alternar claro/oscuro.

### 3. Docstrings prosa + enriquecimiento selectivo
Los docstrings del repo son prosa y mkdocstrings los renderiza bien. **No** se
retrofita a Google-style masivamente (cientos de docstrings, bajo valor); la
referencia funciona con la prosa existente.

### 4. La doc no puede pudrirse (CI)
`.github/workflows/docs.yml` ejecuta en cada push/PR: `mkdocs build --strict`
(falla ante warnings/enlaces rotos/docstrings rotos), los **bloques de código de
los tutoriales** con `pytest-markdown-docs`, y los **ejemplos** con `pytest`. El
sitio se publica como artifact.

## Consecuencias
- **Positivas:** documentación completa (arquitectura con Mermaid, 6 guías de
  extensión, 4 tutoriales ejecutables, referencia autogenerada, 3 ejemplos
  ejecutables), 100 % offline, validada en CI. Los 29 ADRs se reutilizan como
  sección de decisiones.
- **Negativas:** los desarrolladores deben mantener docstrings correctos y los
  bloques ejecutables de los tutoriales autocontenidos (los ilustrativos se marcan
  `{.python notest}`).
- En español, coherente con todo el repositorio.
