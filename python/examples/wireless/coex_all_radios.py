"""All three radios on one classic ESP32: Bluetooth link + ESP-NOW + Wi-Fi AP.

The board runs heap-thin like this; big transfers (files, OTA) are refused
until a radio is released. Run espnow_broadcast.py on another board to hear it.

    uv run wireless/coex_all_radios.py
"""
import time

from esplink import Bridge

with Bridge(ble=True) as esp:
    esp.espnow.begin()
    esp.wifi.ap_start("esplink-coex", "coex12345")
    print(f"all radios up, {esp.free_heap()['free']} B heap free")
    for n in range(30):
        esp.espnow.broadcast(f"coex tick {n}".encode())
        time.sleep(1)
    esp.wifi.ap_stop()
    esp.espnow.end()
