"""DHT22 (or DHT11) temperature + humidity on GPIO 4 (10k pull-up to 3V3 helps).

    uv run devices/dht_read.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    sensor = esp.dht(pin=4, model=22)        # model=11 for the blue DHT11
    for _ in range(10):
        temp, hum = sensor.read()
        print(f"{temp:.1f} C  {hum:.1f} %RH")
        time.sleep(2)
