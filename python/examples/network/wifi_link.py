"""Control a board over Wi-Fi instead of a cable.

Provision once over USB: the board stores the credentials and rejoins on every
boot. Afterwards connect with Bridge(wifi=True), or Bridge(host="192.168.1.50").

    uv run network/wifi_link.py
"""
from esplink import Bridge

SSID, PASSWORD = "your-ssid", "your-password"

with Bridge(ble=False) as usb:              # once, over the cable
    usb.wifi.link_setup(SSID, PASSWORD)

with Bridge(wifi=True) as esp:              # from now on, no cable needed
    print(f"{esp.info.ident} over Wi-Fi, ping {esp.ping() * 1000:.1f} ms")
