"""Talks to the Pico over a serial port (USB, or the HC-06's Bluetooth COM port).

Sending 'g' asks the firmware for its GUI data stream:
    $HEADER,uptime_ms,utc_date,...      column names, sent once when the stream starts
    $DATA,123456,2026-11-03,...         one reading per line, same columns as the SD card CSV
Any other line (">> SD card: ...", status text) is passed along as a message.
Sending 'x' stops the stream.
"""
import time

import serial
import serial.tools.list_ports
from PySide6.QtCore import QThread, Signal

PICO_USB_VID = 0x2E8A  # Raspberry Pi's USB vendor ID


def list_ports():
    """Available serial ports as (device, label) pairs, with the Pico's USB port first."""
    ports = sorted(serial.tools.list_ports.comports(),
                   key=lambda p: (p.vid != PICO_USB_VID, p.device))
    result = []
    for p in ports:
        label = f"{p.device} - {p.description}"
        if p.vid == PICO_USB_VID:
            label += "  [Pico]"
        result.append((p.device, label))
    return result


class StreamParser:
    """Turns raw bytes from the Pico into ("header" | "data" | "message", payload) events.

    Kept separate from the serial port so it can be tested without hardware.
    """

    def __init__(self):
        self.columns = None
        self._buffer = b""

    def feed(self, chunk):
        self._buffer += chunk
        events = []
        while b"\n" in self._buffer:
            raw, self._buffer = self._buffer.split(b"\n", 1)
            line = raw.decode("ascii", errors="replace").strip()
            if line:
                events.append(self._parse_line(line))
        return events

    def _parse_line(self, line):
        if line.startswith("$HEADER,"):
            self.columns = line[len("$HEADER,"):].split(",")
            return ("header", self.columns)
        if line.startswith("$DATA,"):
            values = line[len("$DATA,"):].split(",")
            if self.columns is None:
                return ("need_header", None)
            if len(values) != len(self.columns):
                return ("message", f"Skipped a malformed data line ({len(values)} fields)")
            return ("data", dict(zip(self.columns, values)))
        return ("message", line)


class SerialReader(QThread):
    """Reads the Pico's stream on a background thread so the window never freezes."""

    header_received = Signal(list)
    data_received = Signal(dict)      # column name -> value string ("" if not available)
    message_received = Signal(str)
    failed = Signal(str)              # couldn't open the port, or the device went away

    def __init__(self, port, baud=115200, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud  # ignored for USB; 9600 matters for some Bluetooth adapters

    def run(self):
        try:
            # Opening with DTR on is what tells the Pico's USB serial that a program is listening
            link = serial.Serial(self.port, self.baud, timeout=0.2, write_timeout=1)
        except (serial.SerialException, OSError) as e:
            self.failed.emit(f"Could not open {self.port}.\n\n{e}")
            return

        parser = StreamParser()
        last_header_request = 0.0
        try:
            link.reset_input_buffer()
            link.write(b"g")
            while not self.isInterruptionRequested():
                chunk = link.read(link.in_waiting or 1)
                if not chunk:
                    continue
                for kind, payload in parser.feed(chunk):
                    if kind == "header":
                        self.header_received.emit(payload)
                    elif kind == "data":
                        self.data_received.emit(payload)
                    elif kind == "message":
                        self.message_received.emit(payload)
                    elif kind == "need_header" and time.monotonic() - last_header_request > 1:
                        link.write(b"g")  # we joined mid-stream; ask again for the column names
                        last_header_request = time.monotonic()
        except (serial.SerialException, OSError) as e:
            if not self.isInterruptionRequested():
                self.failed.emit(f"Lost the connection to {self.port}.\n\n{e}")
        finally:
            try:
                link.write(b"x")
            except (serial.SerialException, OSError):
                pass
            link.close()

    def stop(self):
        """Ends the thread and closes the port; safe to call more than once."""
        self.requestInterruption()
        self.wait(2000)
