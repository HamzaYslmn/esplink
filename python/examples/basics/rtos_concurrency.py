"""Slow calls don't stall fast ones: a Wi-Fi scan blocks the board for seconds,
yet pings from another thread keep returning in milliseconds.

The firmware runs slow radio work on its own FreeRTOS task, and requests from
different threads pipeline on one link (docs/PROTOCOL.md). Run over USB: over
Bluetooth the scan would also share the radio with the link itself.

    uv run basics/rtos_concurrency.py
"""
import threading

from esplink import Bridge

with Bridge(ble=False) as esp:
    scan = threading.Thread(target=esp.wifi.scan)
    scan.start()
    worst = 0.0
    while scan.is_alive():
        worst = max(worst, esp.ping())
    print(f"worst ping during the scan: {worst * 1000:.1f} ms")
