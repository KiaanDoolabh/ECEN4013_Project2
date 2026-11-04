"""The GUI's two screens: the main menu and the live data display."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from serial_link import list_ports

ACCURACY_NAMES = {"0": "Unreliable", "1": "Low", "2": "Medium", "3": "High"}


def format_number(text, decimals):
    """'12.3456' -> '12.35'; blank or unparseable -> an em dash."""
    try:
        return f"{float(text):.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


class ValueLabel(QLabel):
    """One big number on the display. Each field has exactly one, updated in place."""

    def __init__(self, parent=None):
        super().__init__("—", parent)
        self.setObjectName("value")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)


class MainMenu(QWidget):
    start_requested = Signal(str)   # chosen port, or "" if there are none
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        title = QLabel("ECEN 4013 Project 2")
        title.setObjectName("title")
        subtitle = QLabel("GPS + IMU live display")
        subtitle.setObjectName("subtitle")

        self.port_box = QComboBox()
        self.port_box.setMinimumWidth(380)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_ports)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Device port:"))
        port_row.addWidget(self.port_box, 1)
        port_row.addWidget(refresh)

        start = QPushButton("Start Display")
        start.setObjectName("primary")
        start.clicked.connect(lambda: self.start_requested.emit(self.port_box.currentData() or ""))
        quit_button = QPushButton("Quit")
        quit_button.clicked.connect(self.quit_requested)

        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)

        column = QVBoxLayout()
        column.addStretch(1)
        column.addWidget(title, alignment=Qt.AlignHCenter)
        column.addWidget(subtitle, alignment=Qt.AlignHCenter)
        column.addSpacing(30)
        column.addLayout(port_row)
        column.addWidget(self.hint)
        column.addSpacing(20)
        column.addWidget(start)
        column.addWidget(quit_button)
        column.addStretch(2)

        outer = QHBoxLayout(self)
        outer.addStretch(1)
        outer.addLayout(column, 2)
        outer.addStretch(1)

        self.refresh_ports()

    def refresh_ports(self):
        self.port_box.clear()
        ports = list_ports()
        for device, label in ports:
            self.port_box.addItem(label, device)
        if not ports:
            self.port_box.addItem("No serial ports found", "")
            self.hint.setText("Plug the Pico in over USB (or pair the HC-06), then press Refresh.")
        elif "[Pico]" in ports[0][1]:
            self.hint.setText("Pico found on USB and selected.")
        else:
            self.hint.setText("No Pico detected on USB. Pick its Bluetooth COM port, or plug it in "
                              "and press Refresh.")


class DisplayScreen(QWidget):
    end_requested = Signal()
    quit_requested = Signal()

    # (label, CSV column, unit, decimals)
    GPS_FIELDS = [
        ("Latitude", "latitude", "°", 6),
        ("Longitude", "longitude", "°", 6),
        ("Elevation", "altitude_m", "m", 1),
    ]
    # (label, CSV column prefix, unit, decimals); the X/Y/Z columns are prefix + _x etc.
    IMU_VECTORS = [
        ("Angular Velocity", "gyro", "rad/s", 3),
        ("Acceleration", "accel", "m/s²", 2),
        ("Magnetic Field", "mag", "µT", 1),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = {}  # CSV column -> (ValueLabel, decimals)

        # Top bar
        self.connection = QLabel()
        self.connection.setObjectName("connection")
        end = QPushButton("End Display")
        end.setObjectName("primary")
        end.clicked.connect(self.end_requested)
        quit_button = QPushButton("Quit")
        quit_button.clicked.connect(self.quit_requested)
        top = QHBoxLayout()
        top.addWidget(self.connection, 1)
        top.addWidget(end)
        top.addWidget(quit_button)

        sections = QHBoxLayout()
        sections.addWidget(self._build_gps(), 1)
        sections.addWidget(self._build_imu(), 2)

        self.status = QLabel("Waiting for data...")
        self.status.setObjectName("status")

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(sections, 1)
        layout.addWidget(self.status)

    def _value(self, column, decimals):
        label = ValueLabel()
        self.values[column] = (label, decimals)
        return label

    def _build_gps(self):
        box = QGroupBox("GPS")
        grid = QGridLayout(box)
        row = 0
        for name, column, unit, decimals in self.GPS_FIELDS:
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(self._value(column, decimals), row, 1)
            grid.addWidget(QLabel(unit), row, 2)
            row += 1

        grid.addWidget(self._divider(), row, 0, 1, 3)
        row += 1
        self.fix = QLabel("—")
        self.satellites = QLabel("—")
        self.utc = QLabel("—")
        for name, label in (("Fix", self.fix), ("Satellites (used / seen)", self.satellites),
                            ("UTC time", self.utc)):
            label.setObjectName("detail")
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(label, row, 1, 1, 2, Qt.AlignRight)
            row += 1
        grid.setRowStretch(row, 1)
        return box

    def _build_imu(self):
        box = QGroupBox("IMU")
        grid = QGridLayout(box)
        for col, axis in enumerate("XYZ"):
            header = QLabel(axis)
            header.setObjectName("axis")
            header.setAlignment(Qt.AlignRight)
            grid.addWidget(header, 0, col + 1)
        row = 1
        for name, prefix, unit, decimals in self.IMU_VECTORS:
            grid.addWidget(QLabel(name), row, 0)
            for col, axis in enumerate("xyz"):
                grid.addWidget(self._value(f"{prefix}_{axis}", decimals), row, col + 1)
            grid.addWidget(QLabel(unit), row, 4)
            row += 1

        # Orientation gets its own column headings, since its three values aren't X/Y/Z
        for col, name in enumerate(("Yaw", "Pitch", "Roll")):
            header = QLabel(name)
            header.setObjectName("axis")
            header.setAlignment(Qt.AlignRight)
            grid.addWidget(header, row, col + 1)
        row += 1
        grid.addWidget(QLabel("Orientation"), row, 0)
        for col, column in enumerate(("yaw_deg", "pitch_deg", "roll_deg")):
            grid.addWidget(self._value(column, 1), row, col + 1)
        grid.addWidget(QLabel("°"), row, 4)
        row += 1

        grid.addWidget(self._divider(), row, 0, 1, 5)
        row += 1
        self.accuracy = QLabel("—")
        self.accuracy.setObjectName("detail")
        grid.addWidget(QLabel("Heading accuracy"), row, 0)
        grid.addWidget(self.accuracy, row, 1, 1, 4, Qt.AlignRight)
        row += 1
        grid.setRowStretch(row, 1)
        return box

    @staticmethod
    def _divider():
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("divider")
        return line

    # ---- updates ----

    def reset(self, port):
        self.connection.setText(f"Connected to {port}")
        self.status.setText("Waiting for data...")
        for label, _ in self.values.values():
            label.setText("—")
        for label in (self.fix, self.satellites, self.utc, self.accuracy):
            label.setText("—")

    def update_data(self, row):
        for column, (label, decimals) in self.values.items():
            label.setText(format_number(row.get(column), decimals))

        self.fix.setText({"1": "Yes", "0": "Searching"}.get(row.get("gps_fix", ""), "No GPS"))
        used, seen = row.get("satellites", ""), row.get("sats_in_view", "")
        self.satellites.setText(f"{used or '0'} / {seen or '0'}" if (used or seen) else "—")
        date, time = row.get("utc_date", ""), row.get("utc_time", "")
        self.utc.setText(f"{date} {time}".strip() or "—")

        self.accuracy.setText(ACCURACY_NAMES.get(row.get("heading_accuracy", ""), "—"))

    def set_status(self, text, warning=False):
        self.status.setText(text)
        self.status.setProperty("warning", warning)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
