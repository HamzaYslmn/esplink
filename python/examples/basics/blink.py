"""Blink the on-board LED (GPIO 2 on most classic DevKits).

    uv run basics/blink.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    esp.gpio.mode(2, "output")
    for _ in range(10):
        esp.gpio.write(2, 1)
        time.sleep(0.25)
        esp.gpio.write(2, 0)
        time.sleep(0.25)
