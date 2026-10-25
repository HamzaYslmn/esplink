"""Link speed, same board over USB then Bluetooth: ping latency + 2 KB echo rate.

    uv run wireless/usb_vs_ble_benchmark.py
"""
import statistics
import time

from esplink import Bridge
from esplink import constants as C

for ble in (False, True):
    with Bridge(ble=ble) as esp:
        ping = statistics.median(esp.ping() for _ in range(50)) * 1000
        t0, n = time.perf_counter(), 50
        for _ in range(n):
            esp.ping(bytes(C.MAX_PAYLOAD))           # a full-size frame, out and back
        kbps = n * C.MAX_PAYLOAD * 2 / (time.perf_counter() - t0) / 1000
        print(f"{'BLE' if ble else 'USB'}: ping {ping:.1f} ms, echo {kbps:.0f} KB/s")
