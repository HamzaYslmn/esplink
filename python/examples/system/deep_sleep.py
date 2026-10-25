"""Deep sleep for 10 s, then reconnect and read the wake cause (4 = timer).

Classic ESP32: entering sleep needs IRAM the BLE stack occupies, so it is
refused on a firmware built with BLE (build with BRIDGE_ENABLE_BLE 0, or use
an S2/S3/C3/C6). Light sleep keeps the link: esp.light_sleep(5).

    uv run system/deep_sleep.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    esp.deep_sleep(10)

time.sleep(12)
with Bridge(reset_on_open=False) as esp:     # don't reboot it, or the cause is lost
    print("wake cause:", esp.wake_cause())
