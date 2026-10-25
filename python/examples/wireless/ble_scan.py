"""Use the ESP32 as a BLE scanner: list advertisers nearby for 10 s.

    uv run wireless/ble_scan.py
"""
from esplink import Bridge

with Bridge() as esp:
    for adv in esp.ble.scan(10):
        print(f"{adv.rssi:4d} dBm  {adv.addr}  {adv.name or '-'}")
