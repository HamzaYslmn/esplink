"""Rainbow on a 30-pixel WS2812/NeoPixel strip, data pin on GPIO 5. Ctrl+C stops.

    uv run devices/neopixel_rainbow.py
"""
import colorsys
import itertools
import time

from esplink import Bridge

with Bridge() as esp:
    strip = esp.neopixel(pin=5, n=30, brightness=0.3)
    try:
        for t in itertools.count():
            for i in range(strip.n):
                r, g, b = colorsys.hsv_to_rgb((i / strip.n + t / 100) % 1, 1, 1)
                strip[i] = (int(r * 255), int(g * 255), int(b * 255))
            strip.show()                     # nothing changes until show()
            time.sleep(0.02)
    except KeyboardInterrupt:
        strip.clear()
