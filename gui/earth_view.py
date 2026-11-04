"""Earth view for the Satellites tab: the globe with the satellites placed around it.

The GPS only reports where each satellite is in *your* sky (azimuth and elevation). Knowing
your position and how high each constellation orbits, we follow that line of sight out to
the orbit to get an approximate position in space. Good enough to show where they are;
not an orbit calculation. Drawn with QPainter, orthographic, drag to spin.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

EARTH_RADIUS_KM = 6371.0
# Orbit radius from Earth's center (km). QZSS and BeiDou's high orbits are drawn at the
# top of this range so they stay on screen.
ORBIT_RADIUS_KM = {"G": 26560.0, "R": 25510.0, "E": 29600.0, "C": 27900.0, "J": 29600.0}
VIEW_RADIUS_KM = 30500.0   # what fits in the widget


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(v, k):
    return (v[0] * k, v[1] * k, v[2] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def normalize(v):
    length = math.sqrt(dot(v, v))
    return scale(v, 1 / length)


def earth_point(lat, lon, radius=EARTH_RADIUS_KM):
    """Latitude/longitude in degrees -> Earth-centered x, y, z in km (spherical Earth)."""
    la, lo = math.radians(lat), math.radians(lon)
    return (radius * math.cos(la) * math.cos(lo), radius * math.cos(la) * math.sin(lo),
            radius * math.sin(la))


def satellite_position(lat, lon, azimuth, elevation, orbit_radius):
    """Where the line of sight from (lat, lon) at this azimuth/elevation meets the orbit."""
    la, lo = math.radians(lat), math.radians(lon)
    east = (-math.sin(lo), math.cos(lo), 0.0)
    north = (-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la))
    up = (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))
    az, el = math.radians(azimuth), math.radians(elevation)
    direction = add(add(scale(east, math.cos(el) * math.sin(az)),
                        scale(north, math.cos(el) * math.cos(az))), scale(up, math.sin(el)))
    receiver = earth_point(lat, lon)
    # Solve |receiver + t * direction| = orbit_radius for the positive t
    b = dot(receiver, direction)
    t = -b + math.sqrt(b * b - EARTH_RADIUS_KM ** 2 + orbit_radius ** 2)
    return add(receiver, scale(direction, t))


class EarthView(QWidget):
    satellite_clicked = Signal(object)  # sat key, or None

    def __init__(self, sat_color, sat_key, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self._sat_color, self._sat_key = sat_color, sat_key
        self.sats, self.selected = [], None
        self.receiver = None                 # (lat, lon) once the GPS has a fix
        self.camera_lon, self.camera_lat = None, 20.0
        self._screen = {}                    # sat key -> screen point, for clicking
        self._drag_from = None

    def set_satellites(self, sats, selected):
        self.sats, self.selected = sats, selected
        self.update()

    def set_receiver(self, lat, lon):
        if self.receiver is None:
            # First fix: look at the Earth from a bit to the side of you, so the satellites
            # overhead spread out instead of stacking on top of your marker
            self.camera_lon, self.camera_lat = lon - 60.0, max(-60.0, min(60.0, lat * 0.6 + 10))
        self.receiver = (lat, lon)
        self.update()

    def reset_camera(self):
        if self.receiver:
            lat, lon = self.receiver
            self.receiver = None  # so set_receiver picks the starting viewpoint again
            self.set_receiver(lat, lon)

    def clear(self):
        self.receiver = None
        self.camera_lon = None
        self.update()

    # ---- mouse ----

    def mousePressEvent(self, event):
        self._drag_from = self._press_at = event.position()

    def mouseMoveEvent(self, event):
        if self._drag_from is None or self.camera_lon is None:
            return
        delta = event.position() - self._drag_from
        self._drag_from = event.position()
        self.camera_lon -= delta.x() * 0.4
        self.camera_lat = max(-85.0, min(85.0, self.camera_lat + delta.y() * 0.4))
        self.update()

    def mouseReleaseEvent(self, event):
        moved = (event.position() - self._press_at).manhattanLength() > 4
        self._drag_from = None
        if not moved:  # a click, not a drag: select the satellite under the mouse
            hit = None
            for key, point in self._screen.items():
                if (point - event.position()).manhattanLength() < 16:
                    hit = key
            self.satellite_clicked.emit(hit)

    # ---- drawing ----

    def _camera(self):
        """Screen basis vectors: right, up, and toward-the-viewer."""
        toward = earth_point(self.camera_lat, self.camera_lon, 1.0)
        right = normalize(cross((0.0, 0.0, 1.0), toward))
        up = cross(toward, right)
        return right, up, toward

    def _project(self, cam, p):
        right, up, toward = cam
        k = (min(self.width(), self.height()) / 2 - 14) / VIEW_RADIUS_KM
        return (QPointF(self.width() / 2 + dot(p, right) * k, self.height() / 2 - dot(p, up) * k),
                dot(p, toward))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b1120"))
        self._screen = {}

        if self.receiver is None:
            painter.setPen(QColor("#94a3b8"))
            painter.setFont(QFont(self.font().family(), 12))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Waiting for a GPS fix to place the satellites around the Earth\n"
                             "(Sky view works before a fix)")
            return

        cam = self._camera()
        center, _ = self._project(cam, (0.0, 0.0, 0.0))
        k = (min(self.width(), self.height()) / 2 - 14) / VIEW_RADIUS_KM

        # Faint ring at GPS orbit height for scale
        painter.setPen(QPen(QColor("#1e293b"), 1, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        r_orbit = ORBIT_RADIUS_KM["G"] * k
        painter.drawEllipse(center, r_orbit, r_orbit)
        painter.setPen(QColor("#475569"))
        painter.setFont(QFont(self.font().family(), 8))
        painter.drawText(QPointF(center.x() + r_orbit * 0.72, center.y() - r_orbit * 0.72),
                         "GPS orbit ≈ 20,200 km up")

        lat, lon = self.receiver
        placed = []
        for sat in self.sats:
            pos = satellite_position(lat, lon, sat["azimuth"], max(0, sat["elevation"]),
                                     ORBIT_RADIUS_KM.get(sat["system"], ORBIT_RADIUS_KM["G"]))
            point, depth = self._project(cam, pos)
            placed.append((depth, point, sat))
            self._screen[self._sat_key(sat)] = point
        placed.sort(key=lambda item: item[0])

        # Satellites behind the Earth first, so the globe covers the ones it hides
        for depth, point, sat in placed:
            if depth < 0:
                self._draw_satellite(painter, point, sat, behind=True)

        self._draw_earth(painter, cam, center, EARTH_RADIUS_KM * k)

        you, you_depth = self._project(cam, earth_point(lat, lon))
        if you_depth > 0:
            for depth, point, sat in placed:
                if sat["used"] and depth > 0:
                    color = QColor(self._sat_color(sat))
                    color.setAlpha(150)
                    painter.setPen(QPen(color, 1.3))
                    painter.drawLine(you, point)
            painter.setPen(QPen(QColor("#0b1120"), 1.5))
            painter.setBrush(QColor("#facc15"))
            painter.drawEllipse(you, 5, 5)
            painter.setPen(QColor("#facc15"))
            painter.setFont(QFont(self.font().family(), 10, QFont.Bold))
            painter.drawText(you + QPointF(8, 4), "You")

        for depth, point, sat in placed:
            if depth >= 0:
                self._draw_satellite(painter, point, sat, behind=False)

        painter.setPen(QColor("#64748b"))
        painter.setFont(QFont(self.font().family(), 8))
        painter.drawText(QRectF(8, self.height() - 20, self.width() - 16, 16), Qt.AlignLeft,
                         "Drag to spin · lines go to satellites used in the fix · positions approximate")

    def _draw_earth(self, painter, cam, center, radius):
        shade = QRadialGradient(center + QPointF(-radius * 0.35, -radius * 0.35), radius * 1.4)
        shade.setColorAt(0.0, QColor("#2563eb"))
        shade.setColorAt(1.0, QColor("#0c1f4d"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(shade)
        painter.drawEllipse(center, radius, radius)

        # Latitude/longitude lines on the visible side; the equator a little brighter
        def draw_line(points, pen):
            painter.setPen(pen)
            prev = None
            for p in points:
                screen, depth = self._project(cam, p)
                if prev is not None and depth >= 0 and prev[1] >= 0:
                    painter.drawLine(prev[0], screen)
                prev = (screen, depth)

        grid = QPen(QColor(147, 197, 253, 70), 1)
        for la in (-60, -30, 30, 60):
            draw_line([earth_point(la, lo) for lo in range(0, 365, 5)], grid)
        for lo in range(0, 360, 30):
            draw_line([earth_point(la, lo) for la in range(-90, 95, 5)], grid)
        draw_line([earth_point(0, lo) for lo in range(0, 365, 5)], QPen(QColor(147, 197, 253, 140), 1.2))

        # North pole marker so it's clear which way is up
        pole, depth = self._project(cam, earth_point(90, 0, EARTH_RADIUS_KM * 1.12))
        if depth > -EARTH_RADIUS_KM * 0.3:
            painter.setPen(QColor("#f87171"))
            painter.setFont(QFont(self.font().family(), 9, QFont.Bold))
            painter.drawText(QRectF(pole.x() - 8, pole.y() - 8, 16, 16), Qt.AlignCenter, "N")

    def _draw_satellite(self, painter, point, sat, behind):
        selected = self._sat_key(sat) == self.selected
        color = QColor(self._sat_color(sat))
        if behind or sat["snr"] == 0:
            color.setAlpha(90)
        size = 9 if selected else 6
        if selected:
            painter.setPen(QPen(QColor("white"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(point, size + 5, size + 5)
        painter.setPen(QPen(color, 2))
        painter.setBrush(color if sat["used"] else Qt.NoBrush)
        painter.drawEllipse(point, size, size)
        painter.setPen(QColor("white") if selected else QColor("#64748b" if behind else "#cbd5e1"))
        painter.setFont(QFont(self.font().family(), 10 if selected else 8,
                              QFont.Bold if selected else QFont.Normal))
        painter.drawText(point + QPointF(size + 3, -size + 2), str(sat["prn"]))
