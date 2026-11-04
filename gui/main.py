"""ECEN 4013 Project 2 - desktop GUI for the Pico 2 GPS/IMU logger.

Run with:  python main.py   (see README.md for setup)
"""
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget

from screens import DisplayScreen, MainMenu
from serial_link import SerialReader

FIRST_DATA_TIMEOUT_S = 4   # give up if the device sends nothing this long after connecting
STALE_WARNING_S = 2        # warn on the display if data stops for this long

STYLE = """
QWidget { font-size: 15px; }
QLabel#title { font-size: 34px; font-weight: 600; }
QLabel#subtitle { font-size: 18px; color: palette(mid); }
QLabel#hint { color: palette(mid); }
QLabel#value { font-family: Consolas, monospace; font-size: 26px; font-weight: 600;
               padding: 4px 10px; border-radius: 6px; background: palette(base); }
QLabel#detail { font-family: Consolas, monospace; font-size: 17px; }
QLabel#axis { font-weight: 600; color: palette(mid); padding-right: 10px; }
QLabel#connection { font-weight: 600; }
QLabel#status { color: palette(mid); }
QLabel#status[warning="true"] { color: #d97706; font-weight: 600; }
QGroupBox { font-size: 18px; font-weight: 600; border: 1px solid palette(mid);
            border-radius: 8px; margin-top: 14px; padding: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QPushButton { padding: 8px 18px; }
QPushButton#primary { font-size: 17px; font-weight: 600; padding: 12px 24px; }
QFrame#divider { color: palette(mid); }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECEN 4013 Project 2 - Live Display")
        self.resize(1150, 500)

        self.reader = None
        self.port = ""
        self.last_data_time = None
        self.connect_time = 0.0

        self.menu_screen = MainMenu()
        self.display_screen = DisplayScreen()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.menu_screen)
        self.stack.addWidget(self.display_screen)
        self.setCentralWidget(self.stack)

        self.menu_screen.start_requested.connect(self.start_display)
        self.menu_screen.quit_requested.connect(self.close)
        self.display_screen.end_requested.connect(self.end_display)
        self.display_screen.quit_requested.connect(self.close)

        # File > Quit (Ctrl+Q) works from either screen
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        self.menuBar().addMenu("File").addAction(quit_action)

        # Checks for "nothing arrived after connecting" and "data stopped"
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(250)
        self.watchdog.timeout.connect(self.check_stream)

    # ---- Start / End Display ----

    def start_display(self, port):
        if not port:
            QMessageBox.warning(self, "No device",
                                "No serial ports were found.\n\nPlug the Pico in over USB (or pair "
                                "the HC-06 Bluetooth module) and press Refresh.")
            return

        self.port = port
        self.last_data_time = None
        self.connect_time = time.monotonic()
        self.display_screen.reset(port)
        self.stack.setCurrentWidget(self.display_screen)

        self.reader = SerialReader(port)
        self.reader.data_received.connect(self.on_data)
        self.reader.message_received.connect(self.on_message)
        self.reader.failed.connect(self.on_failed)
        self.reader.start()
        self.watchdog.start()

    def end_display(self):
        self.stop_reader()
        self.menu_screen.refresh_ports()
        self.stack.setCurrentWidget(self.menu_screen)

    def stop_reader(self):
        self.watchdog.stop()
        if self.reader is not None:
            for signal in (self.reader.data_received, self.reader.message_received, self.reader.failed):
                signal.disconnect()
            self.reader.stop()
            self.reader = None

    def fail_back_to_menu(self, message):
        """Graceful failure: explain what went wrong and return to the main menu."""
        self.end_display()
        QMessageBox.warning(self, "No data stream", message)

    # ---- incoming data ----

    def on_data(self, row):
        self.last_data_time = time.monotonic()
        self.display_screen.update_data(row)
        self.display_screen.set_status(f"Receiving live data from {self.port}")

    def on_message(self, text):
        # Device notices such as ">> SD card: logging to LOG004.CSV"
        if text.startswith(">>"):
            self.display_screen.set_status(text[2:].strip())

    def on_failed(self, message):
        self.fail_back_to_menu(message)

    def check_stream(self):
        now = time.monotonic()
        if self.last_data_time is None:
            if now - self.connect_time > FIRST_DATA_TIMEOUT_S:
                self.fail_back_to_menu(
                    f"No data was received from {self.port} within {FIRST_DATA_TIMEOUT_S} seconds.\n\n"
                    "Check that this is the Pico's port and that it is running the project firmware.")
        elif now - self.last_data_time > STALE_WARNING_S:
            self.display_screen.set_status(
                f"No new data for {now - self.last_data_time:.0f} s - check the connection",
                warning=True)

    # ---- closing ----

    def closeEvent(self, event):
        self.stop_reader()  # tells the Pico to stop streaming and releases the port
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
