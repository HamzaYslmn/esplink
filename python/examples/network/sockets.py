"""Internet through the ESP32's radio, not this computer's: HTTP, TCP and UDP.

    uv run network/sockets.py
"""
from esplink import Bridge

SSID, PASSWORD = "your-ssid", "your-password"

with Bridge() as esp:
    print("joined, ip", esp.wifi.connect(SSID, PASSWORD).ip)

    status, body = esp.net.http_get("http://example.com/")
    print(f"HTTP {status}, {len(body)} bytes")

    with esp.net.tcp_connect("example.com", 80) as sock:
        sock.send(b"HEAD / HTTP/1.0\r\nHost: example.com\r\n\r\n")
        print(sock.recv(timeout=10).decode().splitlines()[0])

    with esp.net.udp() as sock:              # NTP: ask Google's time server
        sock.sendto(b"\x1b" + bytes(47), ("216.239.35.0", 123))
        data, _ = sock.recvfrom(timeout=5)
        print("unix time:", int.from_bytes(data[40:44], "big") - 2_208_988_800)

    esp.wifi.disconnect()                    # powers the radio off
