# Empaquetado autónomo del Headless Engine (Fase 3, B7 / H11 diferido).
#
# Multi-stage: se compila un binario nativo y se valida en una imagen de runtime
# LIMPIA, sin Python instalado (prueba de aislamiento del intérprete).
#
# Herramienta: PyInstaller. Es la opción fiable para OR-Tools (empaqueta sus
# librerías nativas C++ .so y protobuf sin fricción). Nuitka fue la primera
# recomendación (H11), pero para OR-Tools PyInstaller es la elección pragmática
# que el plan dejó como fallback; el criterio de éxito es "binario que corre en
# entorno limpio", no la herramienta. Ver ADR-029.

# --- Etapa 1: compilar el binario ---
FROM python:3.14-slim-bookworm AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends binutils \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
COPY packaging ./packaging
RUN pip install --no-cache-dir ".[cli]" pyinstaller
RUN pyinstaller --onefile --clean --name schedule-engine \
      --collect-all ortools \
      packaging/entry.py

# --- Etapa 2: runtime LIMPIO, sin Python ---
FROM debian:bookworm-slim AS runtime
# OR-Tools/CP-SAT usa OpenMP en runtime: libgomp1 es la única lib de sistema extra.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/dist/schedule-engine /usr/local/bin/schedule-engine
# Verificación en tiempo de build: el binario arranca sin Python instalado.
RUN /usr/local/bin/schedule-engine doctor
ENTRYPOINT ["schedule-engine"]
