# Tutorial 4 — Publicar plugins

Tienes una restricción, un importador o un solver. Este tutorial cubre cómo
integrarlo con calidad y compartirlo.

## 1. Añádelo al catálogo canónico (opcional pero recomendado)

Si registras tu restricción en `plugins/constraint_catalog.py`, se podrá activar
por `id` desde `plugins.yaml` / `.bjs` y participar en los Tiers automáticamente:

```python
from scheduling_platform.plugins import CONSTRAINT_CATALOG, plugin_names_in_catalog

# el catálogo es la fuente de verdad: todo plugin instalable tiene una entrada
assert "teacher_gaps" in plugin_names_in_catalog()
assert any(d.id == "SC-02" for d in CONSTRAINT_CATALOG)
```

Un test verifica la **cobertura bidireccional**: todo plugin del repo tiene entrada
en el catálogo y viceversa. Añade la tuya y el test seguirá verde.

## 2. Configúralo por YAML

```yaml
plugins:
  - id: teacher_gaps
    enabled: true
    tier: 1
    weight: 150
```

```bash
schedule-engine config validate --plugins plugins.yaml
```

## 3. Pásalo por el gate de calidad

Todo cambio debe cruzar el pipeline de calidad (formato, lint, tipos estrictos,
tests):

```bash
python scripts/check.py
```

Y, si tu plugin afecta al rendimiento, el gate de regresiones compara contra un
baseline y **falla** si el P50 sube más del 5 % o el score baja:

```bash
python scripts/regression_gate.py
```

## 4. Documenta y ejemplifica

- Añade una página en `docs/sdk_guide/` si introduces un punto de extensión nuevo.
- Añade un proyecto ejecutable en `docs/examples/` con su `README.md`, datos de
  entrada y salida esperada.

## 5. Comparte

El proyecto se distribuye como **binario nativo** (`schedule-engine`) que corre sin
Python (ver [ADR-029](../architecture/decisions.md)). Tu plugin viaja dentro del
binario; el usuario final solo necesita el ejecutable y su `.bjs`.

!!! success "Checklist de publicación"
    - [ ] Entrada en el catálogo (si es una restricción).
    - [ ] Cumple `assert_plugin_contract` / el contrato de la SAL.
    - [ ] `scripts/check.py` en verde.
    - [ ] Guía o ejemplo en `docs/`.
