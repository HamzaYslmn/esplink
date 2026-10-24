"""Blink an LED over Bluetooth — no USB cable.

Power the board from anything (USB charger, battery), then:

    uv run ble_blink.py                     # the only advertising bridge
    uv run ble_blink.py relays              # one specific board, by name
    uv run ble_blink.py c0:49:ef:d0:3f:e0   # ...or by MAC, same argument

`esplink scan --ble` lists every board in range; `esplink set-name relays`
gives one a name so you never have to type a MAC again.

The password defaults to "esplink" — change it via
EspLink.ble.begin("yourpassword") in the firmware and reflash.
"""
import sys
import time

from esplink import Bridge

target = sys.argv[1] if len(sys.argv) > 1 else None   # name or MAC

with Bridge(target, ble=True, password="esplink") as esp:
    print(f"connected over Bluetooth: {esp.info.ident} "
          f"({esp.info.chip.name}), ping {esp.ping() * 1000:.1f} ms")
    esp.gpio.mode(2, "output")
    for _ in range(10):
        esp.gpio.write(2, 1)
        time.sleep(0.25)
        esp.gpio.write(2, 0)
        time.sleep(0.25)
    print("done")
