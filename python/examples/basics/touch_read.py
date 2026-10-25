"""Capacitive touch on GPIO 4 (touch pad T0): poll it, then get pushed events.

Touch a bare wire or PCB pad. On the classic ESP32 the reading DROPS when
touched (on S2/S3 it rises).

    uv run basics/touch_read.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    idle = esp.touch.read(4)
    print(f"idle reading {idle}")

    # Let the board sample it and push one event per touch, no polling.
    esp.watch.add("touch", pin=4, below=idle * 2 // 3, period_ms=50,
                  callback=lambda ev: print(f"touched ({ev.value})"))
    print("touch the pad (10 s) ...")
    time.sleep(10)
