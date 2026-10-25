"""Every board at once: Bridge.all() opens all of them, indexed by name or MAC.

Name a board once (`esplink -p COM7 set-name relays`), then use boards["relays"].
Bridge.all(wifi=True) collects boards over Wi-Fi instead, including ones that dial home.

    uv run basics/many_boards.py
"""
from esplink import Bridge

with Bridge.all() as boards:
    for ident, ms in boards.each(lambda esp: esp.ping() * 1000).items():
        print(f"{ident}: {ms:.1f} ms")
