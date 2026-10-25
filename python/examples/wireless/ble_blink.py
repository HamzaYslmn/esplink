"""Blink the LED over Bluetooth: no cable, power the board from anything.

`esplink scan --ble` lists boards in range. The link password defaults to
"esplink" (set it in the sketch: EspLink.ble.begin("yourpassword")).

    uv run wireless/ble_blink.py
"""
import time

from esplink import Bridge

with Bridge(ble=True) as esp:
    esp.gpio.mode(2, "output")
    for _ in range(10):
        esp.gpio.write(2, 1)
        time.sleep(0.25)
        esp.gpio.write(2, 0)
        time.sleep(0.25)
