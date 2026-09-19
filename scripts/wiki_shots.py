"""Capturas de pantalla para la wiki (`docs/wiki/`).

Abre el colegio de ejemplo —el export seudonimizado de las pruebas, sin ningún
dato personal—, le añade guardias de recreo y una ausencia para que esas dos
ventanas tengan algo que enseñar, y guarda un PNG por ventana en
`docs/wiki/img/`.

Uso:  .venv\\Scripts\\python.exe scripts\\wiki_shots.py [--windows clave,clave]

Necesita una pantalla (no funciona con QT_QPA_PLATFORM=offscreen en todos los
temas); si la máquina no tiene, exporta `QT_QPA_PLATFORM=minimal` y revisa el
resultado, porque algunos estilos no se dibujan.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from scheduling_platform.application import OptimizeRequest, UntisService, UntisSession
from scheduling_platform.untis_model import format_date, parse_date
from untis_desktop.qt_bridge import FacadeBridge
from untis_desktop.registry import WindowSpec, load_windows

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "tests" / "fixtures" / "untis_anon.xml"
OUT = ROOT / "docs" / "wiki" / "img"

#: Tamaño de la captura de cada ventana: el que hace legible su contenido.
SIZES: dict[str, tuple[int, int]] = {
    "start": (1180, 760),
    "classes": (1180, 560),
    "teachers": (1180, 560),
    "rooms": (1100, 520),
    "subjects": (1100, 520),
    "departments": (1000, 420),
    "student_groups": (1000, 420),
    "time_grids": (1180, 640),
    "requests": (1180, 620),
    "lessons": (1240, 640),
    "weighting": (1180, 680),
    "optimization": (1100, 620),
    "evaluation": (1180, 620),
    "diagnosis": (1100, 600),
    "planning": (1280, 760),
    "timetables": (1280, 760),
    "supervision": (1240, 640),
    "substitution": (1280, 700),
    "settings": (900, 520),
}


def _lunes_del_curso(session: UntisSession) -> str:
    """Un lunes dentro del curso del proyecto: fuera de él no hay clases."""
    escuela = session.project.school
    inicio = escuela.school_year_begin or escuela.term_begin
    if not inicio:
        return format_date(date.today())
    dia = parse_date(inicio) + timedelta(days=14)
    dia += timedelta(days=(0 - dia.weekday()) % 7)
    return format_date(dia)


def demo_session(svc: UntisService) -> UntisSession:
    """Colegio de ejemplo con horario, guardias y una ausencia del lunes."""
    s = svc.open(EXAMPLE)
    if not s.project.timetables:
        svc.optimize(s, OptimizeRequest(strategy="A", time_limit=20, polish=False))
    grid = s.project.time_grids[0].id if s.project.time_grids else ""
    for zona, nombre in (("Patio", "Patio principal"), ("Pasillos", "Pasillos")):
        svc.add_supervision_area(s, zona, name=nombre, time_grid=grid)
    svc.build_supervision_shifts(s)
    svc.distribute_supervisions(s)
    profe = _profesor_con_mas_clases(s)
    if profe:
        svc.add_absence(s, "teacher", profe, _lunes_del_curso(s), reason="Curso de formación")
    return s


def _profesor_con_mas_clases(session: UntisSession) -> str:
    """El profesor con más horas: así el parte del día tiene algo que enseñar."""
    carga: Counter[str] = Counter()
    for le in session.project.active_lessons:
        for t in le.teachers:
            carga[t] += le.periods_per_week
    return carga.most_common(1)[0][0] if carga else ""


#: Ventanas que calculan en segundo plano y necesitan un respiro (segundos).
SETTLE: dict[str, float] = {"diagnosis": 12.0, "evaluation": 8.0, "planning": 6.0}


def shoot(
    spec: WindowSpec, bridge: FacadeBridge, app: QApplication, dia_demo: str = ""
) -> Path | None:
    """Crea la ventana, la deja dibujada y guarda su PNG."""
    ancho, alto = SIZES.get(spec.key, (1100, 600))
    ventana: QWidget = spec.factory(bridge)
    ir_al_dia = getattr(ventana, "set_date", None)
    if callable(ir_al_dia) and dia_demo:
        ir_al_dia(dia_demo)
    ventana.resize(ancho, alto)
    ventana.show()
    espera = SETTLE.get(spec.key, 0.5)
    final = time.monotonic() + espera
    while time.monotonic() < final:
        app.processEvents()
        time.sleep(0.05)
    destino = OUT / f"{spec.key}.png"
    imagen = ventana.grab()
    ventana.close()
    if imagen.isNull():
        return None
    imagen.save(str(destino), "PNG")
    return destino


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", default="", help="claves separadas por comas")
    args = parser.parse_args(argv[1:])
    if not EXAMPLE.is_file():
        print(f"No encuentro el colegio de ejemplo: {EXAMPLE}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    specs = load_windows()
    pedidas = {c.strip() for c in args.windows.split(",") if c.strip()}
    svc = UntisService()
    sesion = demo_session(svc)
    bridge = FacadeBridge(svc)
    bridge.attach(sesion)
    app.processEvents()

    hechas = 0
    for spec in specs:
        if pedidas and spec.key not in pedidas:
            continue
        destino = shoot(spec, bridge, app, _lunes_del_curso(sesion))
        if destino is None:
            print(f"  sin imagen: {spec.key}", file=sys.stderr)
            continue
        hechas += 1
        print(f"  {spec.key} -> {destino.relative_to(ROOT)}")
    print(f"{hechas} captura(s) en {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
