"""Satellites tab: where each satellite is, and a list with signal strength.

Two pictures of the same satellites, switchable:
  Earth view - the globe with the satellites placed around it (needs a GPS fix)
  Sky view   - looking straight up: the outer ring is the horizon, the center is
               directly overhead, north at the top
Click a satellite (in either picture or in the list) to highlight it everywhere.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from earth_view import EarthView

# Constellation code -> (name, color)
SYSTEMS = {
    "G": ("GPS", "#3b82f6"),
    "R": ("GLONASS", "#ef4444"),
    "E": ("Galileo", "#a855f7"),
    "C": ("BeiDou", "#f59e0b"),
    "J": ("QZSS", "#14b8a6"),
}
MAX_SNR = 50  # dB-Hz; a full signal bar. Good signals are roughly 35-50.


def sat_name(sat):
    return f"{SYSTEMS.get(sat['system'], ('?', ''))[0]} {sat['prn']}"


def sat_key(sat):
    return (sat["system"], sat["prn"])


def sat_color(sat):
    return QColor(SYSTEMS.get(sat["system"], ("", "#94a3b8"))[1])


class SkyPlot(QWidget):
    satellite_clicked = Signal(object)  # sat_key, or None for empty space

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.sats = []
        self.selected = None

    def set_satellites(self, sats, selected):
        self.sats, self.selected = sats, selected
        self.update()

    def _geometry(self):
        radius = min(self.width(), self.height()) / 2 - 28
        return QPointF(self.width() / 2, self.height() / 2), radius

    def _position(self, sat):
        center, radius = self._geometry()
        r = (90 - max(0, min(90, sat["elevation"]))) / 90 * radius
        a = math.radians(sat["azimuth"])
        return QPointF(center.x() + r * math.sin(a), center.y() - r * math.cos(a))

    def mousePressEvent(self, event):
        hit = None
        for sat in self.sats:
            if (self._position(sat) - event.position()).manhattanLength() < 16:
                hit = sat_key(sat)
        self.satellite_clicked.emit(hit)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f172a"))
        center, radius = self._geometry()

        # Rings at the horizon, 30 and 60 degrees up, plus north-south / east-west lines
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.setBrush(Qt.NoBrush)
        for elevation in (0, 30, 60):
            r = (90 - elevation) / 90 * radius
            painter.drawEllipse(center, r, r)
        painter.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))

        small = QFont(self.font().family(), 8)
        painter.setFont(small)
        painter.setPen(QColor("#64748b"))
        for elevation in (30, 60):
            r = (90 - elevation) / 90 * radius
            painter.drawText(QPointF(center.x() + 4, center.y() - r + 12), f"{elevation}°")

        painter.setFont(QFont(self.font().family(), 12, QFont.Bold))
        for label, dx, dy, color in (("N", 0, -1, "#f87171"), ("E", 1, 0, "#e2e8f0"),
                                     ("S", 0, 1, "#e2e8f0"), ("W", -1, 0, "#e2e8f0")):
            painter.setPen(QColor(color))
            p = QPointF(center.x() + dx * (radius + 15), center.y() + dy * (radius + 15))
            painter.drawText(QRectF(p.x() - 10, p.y() - 10, 20, 20), Qt.AlignCenter, label)

        if not self.sats:
            painter.setPen(QColor("#94a3b8"))
            painter.setFont(QFont(self.font().family(), 12))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "No satellites reported yet\n(the GPS needs a view of the sky)")
            return

        # Unselected first so the highlighted one is drawn on top
        for sat in sorted(self.sats, key=lambda s: sat_key(s) == self.selected):
            self._draw_satellite(painter, sat, sat_key(sat) == self.selected)

    def _draw_satellite(self, painter, sat, selected):
        p = self._position(sat)
        color = sat_color(sat)
        if sat["snr"] == 0:
            color.setAlpha(110)  # in the almanac but not being received
        size = 9 if selected else 7
        if selected:
            painter.setPen(QPen(QColor("white"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(p, size + 5, size + 5)
        painter.setPen(QPen(color, 2))
        painter.setBrush(color if sat["used"] else Qt.NoBrush)  # filled = used in the fix
        painter.drawEllipse(p, size, size)

        painter.setPen(QColor("white") if selected else QColor("#cbd5e1"))
        painter.setFont(QFont(self.font().family(), 10 if selected else 8,
                              QFont.Bold if selected else QFont.Normal))
        painter.drawText(p + QPointF(size + 3, -size + 2), str(sat["prn"]))


class SignalBar(QWidget):
    """A small horizontal bar for one satellite's signal strength, with the number beside it."""

    def __init__(self, snr, color, parent=None):
        super().__init__(parent)
        self.snr, self.color = snr, color
        self.setMinimumWidth(110)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bar = QRectF(4, self.height() / 2 - 5, self.width() - 40, 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#e2e8f0"))
        painter.drawRoundedRect(bar, 3, 3)
        fill = QRectF(bar.x(), bar.y(), bar.width() * min(self.snr, MAX_SNR) / MAX_SNR, bar.height())
        painter.setBrush(self.color)
        painter.drawRoundedRect(fill, 3, 3)
        painter.setPen(QColor("#334155"))
        painter.drawText(QRectF(bar.right() + 4, 0, 32, self.height()), Qt.AlignVCenter,
                         str(self.snr) if self.snr else "—")


class SatellitesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sats = []
        self.selected = None

        self.earth = EarthView(sat_color, sat_key)
        self.earth.satellite_clicked.connect(self._select)
        self.sky = SkyPlot()
        self.sky.satellite_clicked.connect(self._select)
        self.views = QStackedWidget()
        self.views.addWidget(self.earth)
        self.views.addWidget(self.sky)

        # Earth / Sky switch, plus a button to put the globe back where it started
        switch = QHBoxLayout()
        group = QButtonGroup(self)
        for index, (name, tip) in enumerate((
                ("Earth view", "The satellites around the globe"),
                ("Sky view", "Looking straight up from where you are"))):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setToolTip(tip)
            group.addButton(button, index)
            switch.addWidget(button)
        group.idClicked.connect(self.views.setCurrentIndex)
        switch.addStretch(1)
        reset = QPushButton("Reset View")
        reset.clicked.connect(self.earth.reset_camera)
        switch.addWidget(reset)

        self.legend = QLabel()
        self.legend.setTextFormat(Qt.RichText)
        self.legend.setAlignment(Qt.AlignCenter)
        left = QVBoxLayout()
        left.addLayout(switch)
        left.addWidget(self.views, 1)
        left.addWidget(self.legend)

        self.summary = QLabel("—")
        self.summary.setObjectName("detail")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Satellite", "Signal (dB-Hz)", "Used"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._table_selection_changed)
        self.details = QLabel("Click a satellite to see where it is")
        self.details.setWordWrap(True)

        right = QVBoxLayout()
        right.addWidget(self.summary)
        right.addWidget(self.table, 1)
        right.addWidget(self.details)

        layout = QHBoxLayout(self)
        layout.addLayout(left, 3)
        layout.addLayout(right, 2)
        self._refresh_legend()

    # ---- updates ----

    def update_satellites(self, sats):
        # Used ones first, then strongest signal
        self.sats = sorted(sats, key=lambda s: (not s["used"], -s["snr"], s["system"], s["prn"]))
        used = sum(s["used"] for s in sats)
        self.summary.setText(f"{used} used in fix  /  {len(sats)} in view")
        self._fill_table()
        self._refresh_legend()
        self._show_selection()

    def set_receiver(self, lat, lon):
        """Your position, needed to place the satellites around the globe."""
        self.earth.set_receiver(lat, lon)

    def reset(self):
        self.selected = None
        self.earth.clear()
        self.update_satellites([])
        self.summary.setText("—")

    def _fill_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.sats))
        for row, sat in enumerate(self.sats):
            name = QTableWidgetItem(f"●  {sat_name(sat)}")
            name.setForeground(sat_color(sat))
            name.setData(Qt.UserRole, sat_key(sat))
            name.setToolTip(f"Elevation {sat['elevation']}°, azimuth {sat['azimuth']}°")
            self.table.setItem(row, 0, name)
            self.table.setCellWidget(row, 1, SignalBar(sat["snr"], sat_color(sat)))
            used = QTableWidgetItem("✓" if sat["used"] else "")
            used.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, used)
            if sat_key(sat) == self.selected:
                self.table.selectRow(row)
        if self.selected not in {sat_key(s) for s in self.sats}:
            self.table.clearSelection()
        self.table.blockSignals(False)

    def _refresh_legend(self):
        present = {s["system"] for s in self.sats} or set(SYSTEMS)
        swatches = "&nbsp;&nbsp;&nbsp;".join(
            f"<span style='color:{color}'>●</span> {name}"
            for code, (name, color) in SYSTEMS.items() if code in present)
        self.legend.setText(f"{swatches}<br><span style='color:#64748b'>"
                            "filled = used in fix &nbsp;·&nbsp; hollow = in view only</span>")

    # ---- selection, kept in sync between the plot and the list ----

    def _select(self, key):
        self.selected = key
        self.table.blockSignals(True)
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == key:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0))
        self.table.blockSignals(False)
        self._show_selection()

    def _table_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        key = self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None
        self.selected = tuple(key) if key else None
        self._show_selection()

    def _show_selection(self):
        self.sky.set_satellites(self.sats, self.selected)
        self.earth.set_satellites(self.sats, self.selected)
        sat = next((s for s in self.sats if sat_key(s) == self.selected), None)
        if sat is None:
            self.details.setText("Click a satellite to see where it is")
            return
        signal = f"{sat['snr']} dB-Hz" if sat["snr"] else "not being received"
        self.details.setText(
            f"<b>{sat_name(sat)}</b> – {sat['elevation']}° above the horizon, "
            f"bearing {sat['azimuth']}°, signal {signal}, "
            f"{'used in the fix' if sat['used'] else 'not used in the fix'}")
