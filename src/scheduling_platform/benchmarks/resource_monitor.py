"""Monitor de recursos (RAM y CPU) durante una ejecución (Actividad 3).

Muestrea el proceso actual en un hilo de fondo mientras el motor resuelve, y
reporta RAM pico/promedio (MB) y CPU promedio/máxima (%). Complementa a
``tracemalloc`` (que mide solo la memoria de objetos Python) con la RSS real del
proceso, incluida la del solver nativo.

Uso::

    with ResourceMonitor() as monitor:
        engine.solve(problem, config)
    print(monitor.ram_peak_mb, monitor.cpu_avg_pct)
"""

from __future__ import annotations

import threading
import time

import psutil


class ResourceMonitor:
    """Muestreador de RAM/CPU del proceso actual durante un bloque ``with``."""

    def __init__(self, interval_s: float = 0.05) -> None:
        self._interval = interval_s
        self._process = psutil.Process()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ram_samples: list[float] = []
        self._cpu_samples: list[float] = []

    def __enter__(self) -> ResourceMonitor:
        self._process.cpu_percent(None)  # ceba la medición de CPU (primera lectura = 0)
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        # Garantiza al menos una muestra aunque el bloque fuera muy corto.
        if not self._ram_samples:
            self._ram_samples.append(self._process.memory_info().rss / (1024 * 1024))

    def _sample(self) -> None:
        while not self._stop.is_set():
            try:
                self._ram_samples.append(self._process.memory_info().rss / (1024 * 1024))
                self._cpu_samples.append(self._process.cpu_percent(None))
            except psutil.Error:  # pragma: no cover - el proceso desapareció
                break
            time.sleep(self._interval)

    @property
    def ram_peak_mb(self) -> float:
        return max(self._ram_samples, default=0.0)

    @property
    def ram_avg_mb(self) -> float:
        return sum(self._ram_samples) / len(self._ram_samples) if self._ram_samples else 0.0

    @property
    def cpu_avg_pct(self) -> float:
        util = [c for c in self._cpu_samples if c > 0]  # descarta el 0 de cebado
        return sum(util) / len(util) if util else 0.0

    @property
    def cpu_max_pct(self) -> float:
        return max(self._cpu_samples, default=0.0)
