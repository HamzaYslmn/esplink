"""Make the ESP32 a Wi-Fi access point for 60 s (join "esplink-demo" from a phone).

    uv run network/wifi_ap.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    ip = esp.wifi.ap_start("esplink-demo", "letmein123", channel=6)
    print(f"AP up at {ip}")
    time.sleep(60)
    esp.wifi.ap_stop()                       # gives the ~50 KB of radio heap back
