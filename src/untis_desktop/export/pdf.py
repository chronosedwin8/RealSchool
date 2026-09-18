"""Horarios en PDF: el HTML de `export.html` impreso con `QTextDocument`.

No hace falta impresora: `QPrinter` en modo PDF escribe el archivo directamente.
`print_html` sirve también para una impresora real elegida en `QPrintDialog`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter


def print_html(html: str, printer: QPrinter) -> None:
    """Imprime un documento HTML en la impresora (o PDF) indicada."""
    documento = QTextDocument()
    documento.setHtml(html)
    documento.print_(printer)


def html_to_pdf(html: str, path: str | Path, *, landscape: bool = True) -> Path:
    """Escribe `html` como PDF A4 en `path` y devuelve la ruta."""
    destino = Path(path)
    if destino.suffix.lower() != ".pdf":
        destino = destino.with_suffix(".pdf")
    destino.parent.mkdir(parents=True, exist_ok=True)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(destino))
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(
        QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait
    )
    print_html(html, printer)
    return destino
