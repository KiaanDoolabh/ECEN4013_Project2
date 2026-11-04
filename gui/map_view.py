"""Map tab: where the device is, on a live street or satellite map.

The map is a small Leaflet web page inside a Qt web view, with OpenStreetMap street tiles
and Esri World Imagery satellite tiles (no account or API key needed). It needs an internet
connection; without one the page says so and the coordinates are still shown below it.
"Open in Google Maps" opens the current position in the web browser.
"""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

# OpenStreetMap's tile policy asks apps to identify themselves in the User-Agent
APP_NAME = "ECEN4013-Project2-GUI (+https://github.com/KiaanDoolabh/ECEN4013_Project2)"

MAP_PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
  html, body, #map { height: 100%; margin: 0; background: #0f172a; }
  #msg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
         text-align: center; color: #cbd5e1; font: 16px "Segoe UI", sans-serif; z-index: 1000;
         pointer-events: none; text-shadow: 0 1px 3px #000; }
</style>
</head><body>
<div id="map"></div>
<div id="msg">Waiting for a GPS fix...</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""
        onerror="offline()"></script>
<script>
function offline() {
  var msg = document.getElementById('msg');
  msg.innerHTML = 'The map needs an internet connection.<br>Coordinates are still shown below.';
  msg.style.display = 'flex';
}
var map = null, marker = null, trail = null, follow = true, centered = false;
var tiles = {loaded: 0, failed: 0};   // for troubleshooting a blank map
if (window.L) {
  var street = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    {maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'});
  var satellite = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {maxZoom: 19, attribution: 'Imagery &copy; Esri'});
  [street, satellite].forEach(function (layer) {
    layer.on('tileload', function () { tiles.loaded++; });
    layer.on('tileerror', function () { tiles.failed++; });
  });
  map = L.map('map').setView([39.5, -98.35], 4);   // the US, until the first fix
  street.addTo(map);
  L.control.layers({'Street': street, 'Satellite': satellite}, null, {collapsed: false}).addTo(map);
  L.control.scale({imperial: true, metric: true}).addTo(map);
  trail = L.polyline([], {color: '#2563eb', weight: 3, opacity: 0.8}).addTo(map);
  marker = L.circleMarker([0, 0], {radius: 8, color: '#ffffff', weight: 3,
                                   fillColor: '#dc2626', fillOpacity: 1});
  // Dragging the map yourself turns off follow mode so it stops snapping back
  map.on('dragstart', function () { follow = false; window.followChanged = true; });
}
function updatePosition(lat, lon, addToTrail) {
  if (!map) return;
  document.getElementById('msg').style.display = 'none';
  marker.setLatLng([lat, lon]);
  if (!map.hasLayer(marker)) marker.addTo(map);
  if (addToTrail) trail.addLatLng([lat, lon]);
  if (!centered) { map.setView([lat, lon], 17); centered = true; }
  else if (follow) map.panTo([lat, lon]);
}
function setFollow(on) { follow = on; if (on && marker && map.hasLayer(marker)) map.panTo(marker.getLatLng()); }
function clearTrail() { if (trail) trail.setLatLngs(marker && map.hasLayer(marker) ? [marker.getLatLng()] : []); }
function resetMap() {
  if (!map) return;   // offline: keep the "needs internet" message
  centered = false; follow = true;
  trail.setLatLngs([]);
  marker.remove();
  map.setView([39.5, -98.35], 4);
  document.getElementById('msg').innerHTML = 'Waiting for a GPS fix...';
  document.getElementById('msg').style.display = 'flex';
}
function takeFollowChanged() { var c = window.followChanged === true; window.followChanged = false; return c; }
</script>
</body></html>
"""


class MapTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.position = None   # last (lat, lon) with a fix
        self._page_ready = False

        self.web = QWebEngineView()
        profile = self.web.page().profile()
        if APP_NAME not in profile.httpUserAgent():
            profile.setHttpUserAgent(f"{profile.httpUserAgent()} {APP_NAME}")
        self.web.loadFinished.connect(self._page_loaded)
        self.web.setHtml(MAP_PAGE, QUrl("https://localhost/"))

        self.coords = QLabel("No GPS fix yet")
        self.coords.setObjectName("detail")
        self.follow = QCheckBox("Follow device")
        self.follow.setChecked(True)
        self.follow.toggled.connect(lambda on: self._run(f"setFollow({'true' if on else 'false'})"))
        clear = QPushButton("Clear Trail")
        clear.clicked.connect(lambda: self._run("clearTrail()"))
        self.google = QPushButton("Open in Google Maps")
        self.google.setEnabled(False)
        self.google.clicked.connect(self.open_in_google_maps)

        controls = QHBoxLayout()
        controls.addWidget(self.coords, 1)
        controls.addWidget(self.follow)
        controls.addWidget(clear)
        controls.addWidget(self.google)

        layout = QVBoxLayout(self)
        layout.addWidget(self.web, 1)
        layout.addLayout(controls)

    def _page_loaded(self, ok):
        self._page_ready = ok
        if ok and self.position:
            self._run(f"updatePosition({self.position[0]}, {self.position[1]}, true)")

    def _run(self, script, callback=None):
        if self._page_ready:
            if callback:
                self.web.page().runJavaScript(script, 0, callback)
            else:
                self.web.page().runJavaScript(script)

    def update_data(self, row):
        if row.get("gps_fix") != "1":
            if self.position:
                self.coords.setText(f"{self.position[0]:.6f}, {self.position[1]:.6f}  (last fix, searching...)")
            return
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, ValueError):
            return
        moved = (lat, lon) != self.position
        self.position = (lat, lon)
        self.coords.setText(f"{lat:.6f}, {lon:.6f}")
        self.google.setEnabled(True)
        if moved:  # the GPS updates once a second, the stream 10 times; only redraw on change
            self._run(f"updatePosition({lat}, {lon}, true)")
            # If the user dragged the map, untick Follow to match
            self._run("takeFollowChanged()",
                      lambda changed: changed and self.follow.setChecked(False))

    def open_in_google_maps(self):
        if self.position:
            lat, lon = self.position
            QDesktopServices.openUrl(QUrl(f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"))

    def reset(self):
        self.position = None
        self.coords.setText("No GPS fix yet")
        self.google.setEnabled(False)
        self.follow.setChecked(True)
        self._run("resetMap()")
