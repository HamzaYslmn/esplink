"""ESP-NOW broadcast: run it for every board; each shouts a tick per second
and prints what the others send. Ctrl+C stops.

    uv run wireless/espnow_broadcast.py
"""
import itertools
import time

from esplink import Bridge

with Bridge() as esp:
    print("ESP-NOW MAC", esp.espnow.begin())
    esp.espnow.on_receive(lambda src, data, rssi: print(f"[{src} {rssi} dBm] {data!r}"))
    try:
        for n in itertools.count():
            esp.espnow.broadcast(f"{esp.info.ident}: tick {n}".encode())
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        esp.espnow.end()   # gives the Wi-Fi driver's ~50 KB back
