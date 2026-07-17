"""Módulo 2 · Dashboard: portada del proyecto con KPIs y gráficas.

Tarjetas con conteos y calidad (de ``DashboardStats``) más una gráfica de barras
(QtCharts) con el reparto de entidades. Todo sale del motor vía la Fachada.
"""

from __future__ import annotations

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..engine_bridge import EngineBridge

_CARD_QSS = """
QFrame#card { background: palette(base); border: 1px solid palette(mid); border-radius: 8px; }
QLabel#cardValue { font-size: 26px; font-weight: 700; }
QLabel#cardTitle { color: palette(mid); }
"""


class DashboardModule(QWidget):
    """Pantalla inicial: KPIs + gráfica de entidades."""

    def __init__(self, bridge: EngineBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self.setStyleSheet(_CARD_QSS)

        self._title = QLabel("—")
        self._title.setStyleSheet("font-size: 20px; font-weight: 700;")
        self._cards = QGridLayout()
        self._value_labels: dict[str, QLabel] = {}
        cards_row = QWidget()
        cards_row.setLayout(self._cards)

        self._chart = QChart()
        self._chart.legend().setVisible(False)
        chart_view = QChartView(self._chart)
        chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(cards_row)
        layout.addWidget(chart_view, stretch=1)

        self._build_cards()
        bridge.session_changed.connect(self.refresh)

    def _build_cards(self) -> None:
        specs = [
            ("teachers", "Docentes"),
            ("rooms", "Aulas"),
            ("groups", "Grupos"),
            ("subjects", "Materias"),
            ("tasks", "Clases"),
            ("quality", "Calidad"),
        ]
        for col, (key, title) in enumerate(specs):
            frame = QFrame()
            frame.setObjectName("card")
            box = QVBoxLayout(frame)
            value = QLabel("—")
            value.setObjectName("cardValue")
            caption = QLabel(title)
            caption.setObjectName("cardTitle")
            box.addWidget(value)
            box.addWidget(caption)
            self._cards.addWidget(frame, 0, col)
            self._value_labels[key] = value

    def refresh(self) -> None:
        if not self._bridge.has_session:
            return
        stats = self._bridge.dashboard()
        estado = "resuelto" if stats.solved else "sin resolver"
        self._title.setText(f"{stats.project_name}  ·  {estado}")
        self._value_labels["teachers"].setText(str(stats.teachers))
        self._value_labels["rooms"].setText(str(stats.rooms))
        self._value_labels["groups"].setText(str(stats.groups))
        self._value_labels["subjects"].setText(str(stats.subjects))
        self._value_labels["tasks"].setText(str(stats.tasks))
        self._value_labels["quality"].setText(
            f"{stats.quality_score:.0f}" if stats.quality_score is not None else "—"
        )
        self._draw_chart(stats.teachers, stats.rooms, stats.groups, stats.subjects)

    def _draw_chart(self, teachers: int, rooms: int, groups: int, subjects: int) -> None:
        self._chart.removeAllSeries()
        for axis in list(self._chart.axes()):
            self._chart.removeAxis(axis)

        bar_set = QBarSet("Entidades")
        values = [teachers, rooms, groups, subjects]
        for v in values:
            bar_set.append(float(v))
        series = QBarSeries()
        series.append(bar_set)
        self._chart.addSeries(series)
        self._chart.setTitle("Reparto de entidades")

        categories = ["Docentes", "Aulas", "Grupos", "Materias"]
        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        self._chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(0, max(values) + 1 if values else 1)
        self._chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)
