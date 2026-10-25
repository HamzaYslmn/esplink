"""ESP-NOW unicast between two boards on one computer: A pings, B answers pong.

    uv run wireless/espnow_pingpong.py
"""
from esplink import Bridge

BOARD_A, BOARD_B = "relays", "sensors"     # names or MACs

with Bridge(BOARD_A) as a, Bridge(BOARD_B) as b:
    mac_a, mac_b = a.espnow.begin(), b.espnow.begin()
    a.espnow.add_peer(mac_b)
    b.espnow.add_peer(mac_a)
    b.espnow.on_receive(lambda src, data, rssi: b.espnow.send(src, b"pong"))

    for n in range(3):
        acked = a.espnow.send(mac_b, b"ping")             # True = B's radio ACKed
        src, data, rssi = a.espnow.read(timeout=5)
        print(f"#{n}: ping acked={acked}, got {data!r} at {rssi} dBm")
    a.espnow.end()
    b.espnow.end()
