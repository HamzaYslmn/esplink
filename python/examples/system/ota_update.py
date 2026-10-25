"""Reflash the firmware over the link (USB, Bluetooth or Wi-Fi), no boot button.

Needs an OTA partition scheme (e.g. Minimal SPIFFS), flashed once over USB.
Get the .bin from Sketch > Export Compiled Binary.

    uv run system/ota_update.py
"""
from esplink import Bridge

FIRMWARE = "Bridge.ino.bin"

with Bridge() as esp:
    esp.ota.flash(FIRMWARE, progress=lambda done, total: print(f"\r{100 * done // total}%", end=""))
    print("\nflashed; the board is rebooting into the new firmware")
