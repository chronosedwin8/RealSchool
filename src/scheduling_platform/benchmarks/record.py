"""Registro automático y trazable de un experimento (Actividades 5 y 12).

Cada ejecución de benchmarking genera un :class:`BenchmarkRecord` que combina el
esquema de la Actividad 5 (dataset, solver, tiempos, RAM, variables, score...)
con la trazabilidad de la Actividad 12 (commit de Git, versiones de paquetes,
hardware, configuración del solver, fecha/hora, agregados, observaciones). Se
persiste **automáticamente** como JSON (esquema PG-ready: JSONB-compatible) y como
informe Markdown gemelo, para reproducibilidad y auditoría. Nunca a mano.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import psutil

_TRACKED_PACKAGES = ("ortools", "psutil", "pyyaml")


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5, check=False)
        return out.stdout.strip() or "unknown"
    except OSError, subprocess.SubprocessError:  # pragma: no cover - sin git
        return "unknown"


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in _TRACKED_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:  # pragma: no cover
            versions[name] = "n/a"
    return versions


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass(frozen=True, slots=True)
class Provenance:
    """Contexto reproducible del experimento (Actividad 12)."""

    timestamp_iso: str
    git_commit: str
    git_branch: str
    python_version: str
    os: str
    cpu: str
    cpu_cores: int
    ram_total_gb: float
    packages: Mapping[str, str]

    @classmethod
    def capture(cls) -> Provenance:
        return cls(
            timestamp_iso=datetime.now(UTC).isoformat(timespec="seconds"),
            git_commit=_git("rev-parse", "--short", "HEAD"),
            git_branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
            python_version=platform.python_version(),
            os=f"{platform.system()} {platform.release()}",
            cpu=platform.processor() or platform.machine(),
            cpu_cores=psutil.cpu_count(logical=True) or 0,
            ram_total_gb=round(psutil.virtual_memory().total / (1024**3), 1),
            packages=_package_versions(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BenchmarkRecord:
    """Registro inmutable de un experimento de benchmarking."""

    dataset: str
    solver: str
    reps: int
    warmup: int
    config: Mapping[str, Any]
    provenance: Provenance
    aggregates: Mapping[str, Mapping[str, Any]]
    runs: Sequence[Mapping[str, Any]]
    observaciones: str = ""
    schema_version: int = field(default=1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset": self.dataset,
            "solver": self.solver,
            "reps": self.reps,
            "warmup": self.warmup,
            "config": dict(self.config),
            "provenance": self.provenance.to_dict(),
            "aggregates": {k: dict(v) for k, v in self.aggregates.items()},
            "runs": [dict(r) for r in self.runs],
            "observaciones": self.observaciones,
        }

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> BenchmarkRecord:
        prov = doc["provenance"]
        return cls(
            dataset=doc["dataset"],
            solver=doc["solver"],
            reps=doc["reps"],
            warmup=doc["warmup"],
            config=doc["config"],
            provenance=Provenance(**prov),
            aggregates=doc["aggregates"],
            runs=doc["runs"],
            observaciones=doc.get("observaciones", ""),
            schema_version=doc.get("schema_version", 1),
        )

    def filename_stem(self) -> str:
        date = self.provenance.timestamp_iso.replace(":", "").replace("-", "")[:15]
        return f"{date}-{_slug(self.dataset)}-{_slug(self.solver)}"

    def save(self, results_dir: Path) -> Path:
        """Escribe el JSON (y el informe Markdown gemelo). Devuelve la ruta JSON."""
        results_dir.mkdir(parents=True, exist_ok=True)
        stem = self.filename_stem()
        json_path = results_dir / f"{stem}.json"
        json_path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (results_dir / f"{stem}.md").write_text(self.to_markdown(), encoding="utf-8")
        return json_path

    def to_markdown(self) -> str:
        p = self.provenance
        lines = [
            f"# Benchmark — {self.dataset} · {self.solver}",
            "",
            f"- **Fecha:** {p.timestamp_iso}",
            f"- **Commit:** `{p.git_commit}` ({p.git_branch})",
            f"- **Hardware:** {p.cpu}, {p.cpu_cores} hilos, {p.ram_total_gb} GB RAM",
            f"- **SO / Python:** {p.os} / {p.python_version}",
            "- **Paquetes:** " + ", ".join(f"{k} {v}" for k, v in p.packages.items()),
            f"- **Config solver:** {json.dumps(dict(self.config), ensure_ascii=False)}",
            f"- **Repeticiones:** {self.reps} (+{self.warmup} de calentamiento)",
            "",
            "## Agregados (media · mediana · sd · P95 · IC95)",
            "",
            "| Métrica | Media | Mediana | sd | P95 | IC95 |",
            "|---|--:|--:|--:|--:|--|",
        ]
        for metric, stats in self.aggregates.items():
            lines.append(
                f"| {metric} | {stats['mean']:.2f} | {stats['median']:.2f} | "
                f"{stats['stdev']:.2f} | {stats['p95']:.2f} | "
                f"[{stats['ci95_low']:.2f}, {stats['ci95_high']:.2f}] |"
            )
        if self.observaciones:
            lines += ["", "## Observaciones", "", self.observaciones]
        return "\n".join(lines) + "\n"


DEFAULT_RESULTS_DIR = Path("benchmarks") / "results"
