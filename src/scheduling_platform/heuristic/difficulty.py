"""Dificultad de una lección: el orden de la fase de colocación.

Untis coloca primero lo más difícil. La dificultad combina lo mismo que su
manual: períodos por semana, líneas del acople, clases y profesores
implicados, estrechez de las celdas admitidas (tras los deseos -3), escasez de
aulas candidatas y dobles exigidos. Se añade la **saturación** del recurso más
cargado (períodos que debe dar frente a celdas disponibles): un profesor con
33 períodos en 70 celdas es más difícil de encajar que uno con 10.
"""

from __future__ import annotations

from collections import Counter

from .model import Model

#: Las lecciones fijadas se colocan antes que nada.
FIXED_DIFFICULTY = 1e9


def lesson_difficulty(model: Model) -> list[float]:
    """Dificultad de cada lección (índice interno), mayor = más difícil."""
    carga: Counter[int] = Counter()
    celdas: dict[int, int] = {}
    for L in model.lessons:
        if L.duty:
            continue
        n_celdas = len({c for s in L.sids for c in model.s_allowed[s]})
        for r in L.resources:
            carga[r] += L.ppw
            celdas[r] = max(celdas.get(r, 0), n_celdas)
    resultado: list[float] = []
    for L in model.lessons:
        if L.fixed:
            resultado.append(FIXED_DIFFICULTY)
            continue
        if L.duty:
            # Las obligaciones no chocan con nada: van al final.
            resultado.append(-1.0 + L.ppw * 1e-3)
            continue
        total_celdas = 1
        if L.grid >= 0:
            g = model.grids[L.grid]
            total_celdas = max(1, len(g.days) * len(g.teaching))
        admitidas = [len(model.s_allowed[s]) for s in L.sids]
        media = sum(admitidas) / len(admitidas) if admitidas else 0.0
        estrechez = 1.0 - min(1.0, media / total_celdas)
        saturacion = max((carga[r] / max(1, celdas.get(r, 1)) for r in L.resources), default=0.0)
        escasez = sum(
            1.0 / len(line.candidates) for line in L.lines if line.needs_room and line.candidates
        )
        n_clases = len(L.lesson.classes)
        n_profes = len(L.lesson.teachers)
        dobles = L.dp_min or 0
        resultado.append(
            1.0 * L.ppw
            + 2.0 * len(L.lines)
            + 1.0 * (n_clases + n_profes)
            + 10.0 * estrechez
            + 20.0 * saturacion
            + 2.0 * escasez
            + 4.0 * dobles
        )
    return resultado
