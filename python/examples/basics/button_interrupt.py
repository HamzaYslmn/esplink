"""Edge interrupt: a push-button from GPIO 4 to GND calls back into Python.

    uv run basics/button_interrupt.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    esp.gpio.mode(4, "input_pullup")
    esp.gpio.watch(4, edge="falling", debounce_ms=30,
                   callback=lambda ev: print(f"pressed at {ev.micros} µs"))
    print("press the button (30 s) ...")
    time.sleep(30)
