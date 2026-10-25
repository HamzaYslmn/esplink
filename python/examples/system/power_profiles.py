"""Power knobs: trade speed for runtime.

    esp.cpu_freq(80 | 160 | 240)          CPU clock (80 MHz is the radio floor)
    esp.link_power("battery")             BLE link: radio wakes ~2x/s not ~130x/s
    esp.espnow.power_save(window_ms)      ESP-NOW receive duty

Over USB only the CPU knob applies; over Bluetooth the link profile is the
bigger win (docs/PROTOCOL.md, "Power", has measured numbers).

    uv run system/power_profiles.py
"""
import time

from esplink import Bridge


def avg_ping_ms(esp, n: int = 50) -> float:
    t0 = time.perf_counter()
    for _ in range(n):
        esp.ping()
    return (time.perf_counter() - t0) / n * 1000


with Bridge() as esp:
    for mhz in (240, 80, 240):
        esp.cpu_freq(mhz)
        print(f"CPU {mhz:>3} MHz: ping {avg_ping_ms(esp):.2f} ms, "
              f"heap {esp.free_heap()['free']} B free")
