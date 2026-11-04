"""3D orientation viewer: a model of the IMU board that turns with yaw/pitch/roll.

Drawn with QPainter (no OpenGL), so it runs anywhere Qt does. The world frame is the
BNO085's East-North-Up: yaw 0 means the board's X arrow points east, and the angles
are applied in the same Z-Y-X order the firmware uses to compute them.
"""
import math

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

# Board size in model units: X along the board's X arrow, Y across, Z thickness
BOARD_X, BOARD_Y, BOARD_Z = 2.2, 1.4, 0.18
GROUND_Z = -1.0          # height of the compass grid below the board
CAMERA_DISTANCE = 7.0
DEFAULT_CAMERA = (35.0, 35.0)  # azimuth, elevation in degrees
SMOOTHING = 0.25         # fraction of the way to the newest reading per frame (~30 fps)


# ---- small 3D helpers (vectors are (x, y, z) tuples) ----

def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, 0, s), (0, 1, 0), (-s, 0, c))


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def matmul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def apply(m, v):
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3))


def orientation_matrix(yaw, pitch, roll):
    """Board-to-world rotation for angles in degrees (yaw about Z, then pitch Y, then roll X)."""
    return matmul(rot_z(math.radians(yaw)), matmul(rot_y(math.radians(pitch)), rot_x(math.radians(roll))))


def wrap_degrees(a):
    return (a + 180.0) % 360.0 - 180.0


class OrientationView(QWidget):
    """The 3D drawing. Drag with the mouse to look around."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.target = None                 # newest (yaw, pitch, roll) from the device
        self.shown = (0.0, 0.0, 0.0)       # what's drawn, eased toward target
        self.yaw_offset = 0.0
        self.camera_az, self.camera_el = DEFAULT_CAMERA
        self._drag_from = None

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._step)

    # ---- inputs ----

    def set_angles(self, yaw, pitch, roll):
        self.target = (yaw, pitch, roll)

    def clear(self):
        self.target = None
        self.shown = (0.0, 0.0, 0.0)
        self.update()

    def zero_heading(self):
        """Makes the current heading read as 0 so the board appears pointing straight ahead."""
        if self.target is not None:
            self.yaw_offset = self.target[0]

    def reset_camera(self):
        self.camera_az, self.camera_el = DEFAULT_CAMERA
        self.update()

    def displayed_yaw(self):
        return wrap_degrees(self.shown[0])

    def _step(self):
        if self.target is None:
            return
        yaw_t = self.target[0] - self.yaw_offset
        y, p, r = self.shown
        # Ease toward the newest reading; take the short way round for yaw and roll
        y += wrap_degrees(yaw_t - y) * SMOOTHING
        p += (self.target[1] - p) * SMOOTHING
        r += wrap_degrees(self.target[2] - r) * SMOOTHING
        self.shown = (wrap_degrees(y), p, wrap_degrees(r))
        self.update()

    def showEvent(self, event):
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        self._drag_from = event.position()

    def mouseMoveEvent(self, event):
        if self._drag_from is None:
            return
        delta = event.position() - self._drag_from
        self._drag_from = event.position()
        self.camera_az += delta.x() * 0.4
        self.camera_el = max(-80.0, min(80.0, self.camera_el + delta.y() * 0.4))
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag_from = None

    # ---- drawing ----

    def _camera(self):
        return matmul(rot_x(math.radians(self.camera_el)), rot_z(math.radians(-self.camera_az)))

    def _project(self, cam, p):
        """World point -> (screen point, depth). Larger depth is farther away."""
        x, depth, up = apply(cam, p)
        depth += CAMERA_DISTANCE
        scale = min(self.width() * 0.6, self.height()) * 1.9 / depth
        return QPointF(self.width() / 2 + x * scale, self.height() / 2 - up * scale), depth

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f172a"))
        cam = self._camera()

        self._draw_ground(painter, cam)
        if self.target is None:
            painter.setPen(QColor("#94a3b8"))
            painter.setFont(QFont(self.font().family(), 14))
            painter.drawText(self.rect(), Qt.AlignCenter, "Waiting for IMU data...")
            return
        self._draw_board(painter, cam, orientation_matrix(*self.shown))

    def _draw_ground(self, painter, cam):
        grid_pen = QPen(QColor("#334155"), 1)
        painter.setPen(grid_pen)
        extent, step = 2.0, 0.5
        n = int(extent / step)
        for i in range(-n, n + 1):
            t = i * step
            for a, b in (((t, -extent, GROUND_Z), (t, extent, GROUND_Z)),
                         ((-extent, t, GROUND_Z), (extent, t, GROUND_Z))):
                painter.drawLine(self._project(cam, a)[0], self._project(cam, b)[0])

        if self.yaw_offset != 0:
            return  # with the heading zeroed, compass directions no longer line up
        painter.setFont(QFont(self.font().family(), 13, QFont.Bold))
        for label, (x, y), color in (("N", (0, 1), "#f87171"), ("E", (1, 0), "#e2e8f0"),
                                     ("S", (0, -1), "#e2e8f0"), ("W", (-1, 0), "#e2e8f0")):
            point, _ = self._project(cam, (x * (extent + 0.35), y * (extent + 0.35), GROUND_Z))
            painter.setPen(QColor(color))
            painter.drawText(point + QPointF(-5, 5), label)

    def _draw_board(self, painter, cam, rot):
        hx, hy, hz = BOARD_X / 2, BOARD_Y / 2, BOARD_Z / 2
        corners = [(sx * hx, sy * hy, sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        world = [apply(rot, c) for c in corners]

        def idx(sx, sy, sz):
            return ((sx > 0) << 2) | ((sy > 0) << 1) | (sz > 0)

        # (corner indices in order, outward normal in board coordinates, color)
        faces = [
            ([idx(-1, -1, 1), idx(1, -1, 1), idx(1, 1, 1), idx(-1, 1, 1)], (0, 0, 1), QColor("#16a34a")),
            ([idx(-1, -1, -1), idx(-1, 1, -1), idx(1, 1, -1), idx(1, -1, -1)], (0, 0, -1), QColor("#14532d")),
            ([idx(1, -1, -1), idx(1, 1, -1), idx(1, 1, 1), idx(1, -1, 1)], (1, 0, 0), QColor("#64748b")),
            ([idx(-1, -1, -1), idx(-1, -1, 1), idx(-1, 1, 1), idx(-1, 1, -1)], (-1, 0, 0), QColor("#64748b")),
            ([idx(-1, 1, -1), idx(-1, 1, 1), idx(1, 1, 1), idx(1, 1, -1)], (0, 1, 0), QColor("#475569")),
            ([idx(-1, -1, -1), idx(1, -1, -1), idx(1, -1, 1), idx(-1, -1, 1)], (0, -1, 0), QColor("#475569")),
        ]
        light = (0.35, -0.5, 0.8)
        light_len = math.sqrt(sum(c * c for c in light))
        drawn = []
        for indices, normal, color in faces:
            n_world = apply(rot, normal)
            if apply(cam, n_world)[1] >= 0:   # facing away from the camera
                continue
            brightness = 0.45 + 0.55 * max(0.0, sum(a * b for a, b in zip(n_world, light)) / light_len)
            points = [self._project(cam, world[i]) for i in indices]
            depth = sum(d for _, d in points) / len(points)
            drawn.append((depth, QPolygonF([p for p, _ in points]),
                          QColor.fromRgbF(color.redF() * brightness, color.greenF() * brightness,
                                          color.blueF() * brightness), normal))
        drawn.sort(key=lambda f: f[0], reverse=True)   # far faces first

        painter.setPen(QPen(QColor("#0b1220"), 1.2))
        for _, polygon, color, normal in drawn:
            painter.setBrush(color)
            painter.drawPolygon(polygon)
            if normal == (0, 0, 1):
                self._draw_axes_on_top(painter, cam, rot, hz)

    def _draw_axes_on_top(self, painter, cam, rot, hz):
        """The X and Y arrows printed on the board, as on the real BNO085 breakout."""
        z = hz + 0.002
        for (tip, label, color) in (((0.85, 0, z), "X", "#f87171"), ((0, 0.5, z), "Y", "#60a5fa")):
            start, _ = self._project(cam, apply(rot, (0, 0, z)))
            end, _ = self._project(cam, apply(rot, tip))
            painter.setPen(QPen(QColor(color), 3, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(start, end)
            painter.setFont(QFont(self.font().family(), 12, QFont.Bold))
            painter.drawText(end + QPointF(4, -4), label)
        painter.setPen(QPen(QColor("#0b1220"), 1.2))


class OrientationTab(QWidget):
    """The tab: the 3D view plus a readout and its two buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = OrientationView()

        self.readout = QLabel("—")
        self.readout.setObjectName("detail")
        self.zero = QPushButton("Zero Heading")
        self.zero.setToolTip("Treat the current direction as straight ahead (click again to undo)")
        self.zero.clicked.connect(self._toggle_zero)
        reset = QPushButton("Reset View")
        reset.setToolTip("Put the camera back where it started (drag the view to look around)")
        reset.clicked.connect(self.view.reset_camera)

        controls = QHBoxLayout()
        controls.addWidget(self.readout, 1)
        controls.addWidget(QLabel("Drag to look around"))
        controls.addWidget(self.zero)
        controls.addWidget(reset)

        layout = QVBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addLayout(controls)

    def _toggle_zero(self):
        if self.view.yaw_offset == 0:
            self.view.zero_heading()
        else:
            self.view.yaw_offset = 0.0
        self.zero.setText("Use Compass Heading" if self.view.yaw_offset else "Zero Heading")

    def update_data(self, row):
        try:
            yaw, pitch, roll = (float(row[k]) for k in ("yaw_deg", "pitch_deg", "roll_deg"))
        except (KeyError, ValueError):
            self.readout.setText("No IMU data")
            return
        self.view.set_angles(yaw, pitch, roll)
        heading = "" if self.view.yaw_offset == 0 else "  (heading zeroed)"
        self.readout.setText(f"Yaw {yaw:6.1f}°   Pitch {pitch:6.1f}°   Roll {roll:6.1f}°{heading}")

    def reset(self):
        self.view.clear()
        self.view.yaw_offset = 0.0
        self.zero.setText("Zero Heading")
        self.readout.setText("—")
