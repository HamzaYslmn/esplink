"""luma.oled through the bridge — for projects already built on luma.

Identical to luma on a Raspberry Pi except the serial interface line:
``i2c(port=1, address=0x3C)`` becomes ``LumaI2C(esp.i2c, 0x3C)``.

    uv run compat/luma/oled.py
"""
import time

from luma.core.render import canvas
from luma.oled.device import ssd1306

from esplink import Bridge
from esplink.compat.luma import LumaI2C

with Bridge() as esp:
    esp.i2c.init(sda=21, scl=22)
    device = ssd1306(LumaI2C(esp.i2c, 0x3C), width=128, height=64)
    device.persist = True

    with canvas(device) as draw:
        draw.text((0, 10), "luma.oled via esplink", fill="white")
        draw.rectangle((0, 30, 127, 50), outline="white")
    time.sleep(5)
