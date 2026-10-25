"""List the Wi-Fi networks the ESP32 can see.

    uv run network/wifi_scan.py
"""
from esplink import Bridge

with Bridge() as esp:
    for net in esp.wifi.scan():
        print(f"{net.rssi:4d} dBm  ch{net.channel:<2d}  {net.auth:13s}  {net.ssid}")
