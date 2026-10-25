"""On-device watch rules: the board samples a pin and pushes an event only
when a condition trips. No host polling; works over USB, BLE or Wi-Fi.

Rule 1: ADC GPIO 34 above 2.6 V. Rule 2: GPIO 15 high; it also drives
GPIO 26 on the board itself (do/undo), with no host round trip.

    uv run basics/watch_threshold.py
"""
import time

from esplink import Bridge


def show(ev):
    print(f"rule {ev.id}: {'tripped' if ev.active else 'cleared'} (value {ev.value})")


with Bridge() as esp:
    esp.watch.add("adc_mv", pin=34, above=2600, hysteresis=100, callback=show)
    esp.gpio.mode(15, "input_pulldown")
    esp.watch.add("gpio", pin=15, equals=1, callback=show,
                  do=("gpio", 26, 1), undo=("gpio", 26, 0))
    print("drive GPIO 34 / 15 (30 s) ...")
    time.sleep(30)
    esp.watch.clear()
