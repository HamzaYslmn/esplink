"""CAN bus monitor that also sends a heartbeat frame every second. Ctrl+C stops.

Needs a 3.3 V CAN transceiver (e.g. SN65HVD230): TX -> GPIO 21, RX -> GPIO 22.

    uv run devices/can_dump.py
"""
import itertools
import time

from esplink import Bridge

with Bridge() as esp:
    esp.can.begin(tx=21, rx=22, bitrate=500_000)
    esp.can.on_message(print)                # e.g. "CAN 123 [2] 01 02"
    try:
        for n in itertools.count():
            esp.can.send(0x7FF, (n & 0xFFFF).to_bytes(2, "big"))
            time.sleep(1)
    except KeyboardInterrupt:
        esp.can.end()
