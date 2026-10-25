"""The classic Raspberry Pi MCP3008 spidev script — unchanged, on an ESP32.

    uv run python -m esplink.compat compat/spidev/mcp3008.py

``spidev.SpiDev().open(0, 0)`` becomes SPI host 0 with chip select CE0 =
GPIO5 (CE1 = GPIO15). From your own code: ``from esplink.compat.spidev
import SpiDev`` and ``SpiDev(esp)``. For plain analog reads the ESP32's own
ADC (``esp.adc.read_mv(34)``) needs no MCP3008 at all.

Wiring: MCP3008 CLK -> GPIO18, DOUT -> GPIO19, DIN -> GPIO23, CS -> GPIO5,
VDD/VREF -> 3V3, AGND/DGND -> GND; a potentiometer wiper on CH0.
"""
import time

import spidev

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1_350_000


def read_channel(ch):
    r = spi.xfer2([1, (8 + ch) << 4, 0])  # start bit, single-ended, channel
    return ((r[1] & 3) << 8) | r[2]


try:
    while True:
        v = read_channel(0)
        print(f"CH0 = {v:4d}  ({v * 3.3 / 1023:.2f} V)")
        time.sleep(0.5)
except KeyboardInterrupt:
    pass
finally:
    spi.close()
