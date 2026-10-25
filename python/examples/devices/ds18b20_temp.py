"""DS18B20 1-Wire thermometers on GPIO 4: every probe on the bus.

Needs a 4.7k pull-up from the data line to 3V3.

    uv run devices/ds18b20_temp.py
"""
from esplink import Bridge
from esplink.drivers.ds18b20 import DS18B20

with Bridge() as esp:
    for rom in DS18B20.discover(esp, pin=4):
        print(f"{rom}: {DS18B20(esp, 4, rom).read():.2f} C")
