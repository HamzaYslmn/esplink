"""Trade speed for battery life: slower CPU clock and a relaxed Bluetooth link.

link_power("battery") wakes the radio ~2x/s instead of ~130x/s, at ~0.3-1 s
per command (measured numbers: docs/PROTOCOL.md, "Power").

    uv run system/power_profiles.py
"""
from esplink import Bridge

with Bridge(ble=True) as esp:
    print(f"performance: ping {esp.ping() * 1000:.0f} ms")
    esp.cpu_freq(80)                         # 80 MHz is the floor with a radio on
    esp.link_power("battery")
    print(f"battery:     ping {esp.ping() * 1000:.0f} ms")
