"""OLED drawing over Bluetooth — no USB cable, no COM port.

Each show() costs one BLE round trip (~30 ms) and sends only what changed, so
small updates run near 30 fps.

    uv run displays/ble_oled.py
"""
import time

from esplink import Bridge
from esplink.drivers.oled import OLED

BOARD = None             # name or MAC; None = first board found
SDA, SCL = 1, 2          # your wiring (any GPIOs)

with Bridge(BOARD, ble=True) as esp:
    oled = OLED(esp, sda=SDA, scl=SCL)
    t0, frames = time.monotonic(), 0
    while (elapsed := time.monotonic() - t0) < 30:
        with oled.draw() as d:
            d.text((0, 10), "Hello over BLE!", fill=1)
            d.text((0, 30), f"frame {frames}", fill=1)
            d.rectangle((0, 56, int(127 * elapsed / 30), 62), fill=1)
        frames += 1
    print(f"{frames / 30:.1f} fps")
