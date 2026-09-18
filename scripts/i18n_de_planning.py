"""Rellena las traducciones al alemán pendientes del `.ts` (una sola vez por texto).

Uso: .venv\\Scripts\\python.exe scripts\\i18n_de_planning.py

Recorre `untis_desktop_de.ts`, completa las entradas sin terminar cuyo texto
fuente está en `DE` y deja las demás como estaban. Luego ejecutar
`scripts/i18n.py --release-only` para compilar el `.qm`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

TS = Path(__file__).resolve().parent.parent / "src/untis_desktop/translations/untis_desktop_de.ts"

DE: dict[str, str] = {
    "Diagnóstico": "Diagnose",
    "Cantidad": "Anzahl",
    "Suma": "Summe",
    "Sin proyecto": "Kein Projekt",
    "Períodos sin colocar": "Nicht verplante Stunden",
    "Choques de profesores": "Lehrerkollisionen",
    "Choques de clases": "Klassenkollisionen",
    "Choques de aulas": "Raumkollisionen",
    "Datos de entrada": "Eingabedaten",
    "Horario": "Stundenplan",
    "{0} error(es), {1} advertencia(s)": "{0} Fehler, {1} Warnung(en)",
    "Número de evaluación": "Bewertungszahl",
    "Choques": "Kollisionen",
    "Puntos blandos": "Weiche Punkte",
    "Desglose por criterio": "Aufschlüsselung nach Kriterium",
    "Criterio": "Kriterium",
    "Pestaña": "Registerkarte",
    "Deslizador": "Regler",
    "Peso": "Gewicht",
    "Violaciones": "Verstöße",
    "Puntos": "Punkte",
    "Horarios generados": "Erzeugte Stundenpläne",
    "Activo": "Aktiv",
    "Id": "Id",
    "Nombre": "Name",
    "Evaluación": "Bewertung",
    "Sin colocar": "Nicht verplant",
    "Activar": "Aktivieren",
    "Borrar": "Löschen",
    "Comparar": "Vergleichen",
    "Comparación": "Vergleich",
    "Sin horario activo": "Kein aktiver Stundenplan",
    "Horario: {0}": "Stundenplan: {0}",
    "Activar horario": "Stundenplan aktivieren",
    "Diferencia": "Differenz",
    "Estrategia": "Strategie",
    "A - rápida": "A - schnell",
    "B - compleja": "B - gründlich",
    "D - colocación %": "D - Verplanung %",
    "E - nocturna": "E - über Nacht",
    "Reparar": "Reparieren",
    "Colocación y pocos intercambios: sirve para detectar errores de datos.": (
        "Verplanung mit wenigen Tauschen: zeigt Fehler in den Daten."
    ),
    "Varios reinicios y pulido: el horario de trabajo.": (
        "Mehrere Neustarts und Feinschliff: der Arbeitsstundenplan."
    ),
    "Coloca solo el % más difícil y deja el resto al pulido CP-SAT.": (
        "Verplant nur den schwierigsten Anteil, den Rest übernimmt CP-SAT."
    ),
    "B repetida muchas veces con límite alto: la versión final.": (
        "B viele Male mit hohem Zeitlimit: die endgültige Fassung."
    ),
    "Corrige choques del horario actual con el mínimo cambio.": (
        "Behebt Kollisionen im aktuellen Plan mit möglichst wenigen Änderungen."
    ),
    "Datos de control": "Steuerdaten",
    "Tiempo máximo": "Maximale Zeit",
    "Semilla": "Startwert",
    "Colocación": "Verplanung",
    "Optimización de profesores": "Lehreroptimierung",
    "Pulido CP-SAT": "CP-SAT-Feinschliff",
    "Iniciar": "Starten",
    "Detener": "Anhalten",
    "Progreso": "Fortschritt",
    "Fase": "Phase",
    "Iteración": "Iteration",
    "Evaluación actual": "Aktuelle Bewertung",
    "Mejor evaluación": "Beste Bewertung",
    "Tiempo": "Zeit",
    "Resultado": "Ergebnis",
    "Abrir Evaluación": "Bewertung öffnen",
    "Abrir Diagnóstico": "Diagnose öffnen",
    "Deteniendo...": "Wird angehalten...",
    "Iniciando...": "Wird gestartet...",
    "Terminado": "Fertig",
    "Detenido": "Angehalten",
    "Error": "Fehler",
    "Clase": "Klasse",
    "Profesor": "Lehrer",
    "Aula": "Raum",
    "Foco:": "Fokus:",
    "{0} {1} {2}: {3} sin colocar": "{0} {1} {2}: {3} nicht verplant",
    "Evaluación: {0} ({1} sin colocar, {2} choques)": (
        "Bewertung: {0} ({1} nicht verplant, {2} Kollisionen)"
    ),
    "Lección {0}": "Unterricht {0}",
    " (fijada)": " (fixiert)",
    " - choque": " - Kollision",
    "Cambio de evaluación: {0:+d}": "Änderung der Bewertung: {0:+d}",
    "Destino posible": "Mögliches Ziel",
    "No cabe: {0}": "Nicht möglich: {0}",
    "Clic para intercambiar": "Klicken zum Tauschen",
    "Lección {0}: {1} destino(s) posible(s)": "Unterricht {0}: {1} mögliche(s) Ziel(e)",
    "fuera de la rejilla": "außerhalb des Zeitrasters",
    "No se está arrastrando nada": "Es wird nichts gezogen",
    "Esa celda no es un destino de la sesión": "Diese Zelle ist kein Ziel der Stunde",
    "La celda está vacía": "Die Zelle ist leer",
    "Elige una celda": "Wähle eine Zelle",
    "Elige la celda con la que intercambiar (Esc cancela)": (
        "Wähle die Zelle zum Tauschen (Esc bricht ab)"
    ),
    "Elige una celda ocupada": "Wähle eine belegte Zelle",
    "Es la misma lección": "Das ist derselbe Unterricht",
    "Desfijar": "Fixierung lösen",
    "Fijar": "Fixieren",
    "Desprogramar (F7)": "Ausplanen (F7)",
    "Intercambiar con...": "Tauschen mit...",
    "Abrir lección {0}": "Unterricht {0} öffnen",
    "Materia": "Fach",
    "Horarios:": "Stundenpläne:",
    "Formato:": "Format:",
    "Letra:": "Schrift:",
    "Completo": "Vollständig",
    "Compacto": "Kompakt",
    "Impresión (sin colores)": "Druck (ohne Farben)",
    "Colores": "Farben",
    "Sincronizar": "Synchronisieren",
    "Imprimir / Exportar": "Drucken / Exportieren",
    "Imprimir...": "Drucken...",
    "PDF del horario...": "Stundenplan als PDF...",
    "HTML del horario...": "Stundenplan als HTML...",
    "Exportar todos (HTML, uno por entidad)...": (
        "Alle exportieren (HTML, je Element eine Datei)..."
    ),
    "Exportar todos (un PDF)...": "Alle exportieren (ein PDF)...",
    "Exportar GPU (MiUntisWeb)...": "GPU exportieren (MiUntisWeb)...",
    "Exportar XML (Untis)...": "XML exportieren (Untis)...",
    "HTML exportado: {0}": "HTML exportiert: {0}",
    "PDF exportado: {0}": "PDF exportiert: {0}",
    "{0} archivo(s) exportado(s) en {1}": "{0} Datei(en) exportiert nach {1}",
    "GPU exportado: {0} archivo(s)": "GPU exportiert: {0} Datei(en)",
    "XML exportado: {0}": "XML exportiert: {0}",
    "Exportar PDF": "PDF exportieren",
    "Exportar HTML": "HTML exportieren",
    "Carpeta de destino": "Zielordner",
    "Carpeta para los archivos GPU": "Ordner für die GPU-Dateien",
    "Exportar XML": "XML exportieren",
}


def main() -> int:
    arbol = ET.parse(TS)
    hechos = 0
    faltan: set[str] = set()
    for msg in arbol.getroot().iter("message"):
        trad = msg.find("translation")
        fuente = msg.findtext("source") or ""
        if trad is None or trad.get("type") in ("vanished", "obsolete"):
            continue
        if trad.get("type") == "unfinished" or not (trad.text or "").strip():
            if fuente in DE:
                trad.text = DE[fuente]
                trad.attrib.pop("type", None)
                hechos += 1
            else:
                faltan.add(fuente)
    arbol.write(TS, encoding="utf-8", xml_declaration=True)
    print(f"Traducidas {hechos}; sin traducción: {len(faltan)} {sorted(faltan)[:10]}")
    return 1 if faltan else 0


if __name__ == "__main__":
    raise SystemExit(main())
