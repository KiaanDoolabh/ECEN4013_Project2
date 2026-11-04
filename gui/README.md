# Desktop GUI

Live display of the Pico's GPS and IMU data, read from its USB serial stream
(the HC-06 Bluetooth COM port works too, at a slower update rate).

## Run

Needs Python 3.10 or newer installed. Double-click **`run.bat`** in this folder.
The first time on a computer it sets up a `.venv` environment and installs the
packages (takes a minute); after that it starts straight away.

From a terminal in this folder, either of these works:

```
run.bat
.venv\Scripts\python main.py
```

(`.venv\Scripts\activate` is blocked by PowerShell's default script policy,
which is why these call the environment's Python directly.)

The Pico must be running the project firmware (`build\Senior_Design_1.uf2`).
Close any serial monitor that has the Pico's port open first, since only one
program can use a COM port at a time.

## Using it

- **Main menu:** the Pico's USB port is picked automatically (marked `[Pico]`).
  Press **Start Display**.
- **Display:** one live value per field for GPS (latitude, longitude, elevation)
  and IMU (angular velocity, acceleration and magnetic field on X/Y/Z).
- **End Display** goes back to the main menu.
- **Quit**, **File > Quit**, **Ctrl+Q** or the window's X close the app at any time.
- If the port can't be opened, or no data arrives within 4 seconds, it shows why
  and returns to the main menu. If data stops mid-display, a warning appears at
  the bottom; unplugging the Pico returns to the menu.

## How it talks to the Pico

On connect the GUI sends `g`. The firmware replies with a column list, then
streams one reading per line (10 per second on USB, 2 per second on Bluetooth):

```
$HEADER,uptime_ms,utc_date,utc_time,gps_fix,latitude,...
$DATA,123456,2026-11-03,14:22:05,1,36.1234567,...
```

The columns are the same as the SD card CSV files. The GUI sends `x` when it
disconnects. Other lines (like `>> SD card: logging to LOG004.CSV`) are shown
in the status line.

## Code layout

| File | What it does |
|---|---|
| `main.py` | Main window: switches screens, start/end/quit, failure handling |
| `screens.py` | The main menu and the live display |
| `serial_link.py` | Background serial reader and the `$HEADER`/`$DATA` parser |

To show another value, add it to `GPS_FIELDS` or `IMU_VECTORS` in `screens.py`
using its CSV column name. Every column in the firmware's `CSV_HEADER` is
already available in each row the display receives.
