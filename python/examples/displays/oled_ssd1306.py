"""SSD1306 I2C OLED over USB, drawn with PIL.

Wiring: SDA, SCL to the GPIOs below, VCC -> 3V3, GND.

    uv run displays/oled_ssd1306.py
"""
import time

from esplink import Bridge
from esplink.drivers.oled import OLED

BOARD = None             # name or MAC; None = first board found
SDA, SCL = 1, 2          # your wiring (any GPIOs)

with Bridge(BOARD, ble=False) as esp:
    oled = OLED(esp, sda=SDA, scl=SCL)
    t0, frames = time.monotonic(), 0
    while (elapsed := time.monotonic() - t0) < 10:
        with oled.draw() as d:
            d.text((0, 10), "Hello, esplink!", fill=1)
            d.text((0, 30), f"frame {frames}", fill=1)
            d.rectangle((0, 56, int(127 * elapsed / 10), 62), fill=1)
        frames += 1
    print(f"{frames / 10:.1f} fps")
