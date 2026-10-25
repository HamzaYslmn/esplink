"""ADC + DAC: ramp the DAC on GPIO 25 and read it back on GPIO 34.

Jumper GPIO 25 -> GPIO 34. Classic ESP32 only (the S2/S3/C3 have no DAC).

    uv run basics/adc_dac.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    for value in range(0, 256, 32):
        esp.dac.write(25, value)
        time.sleep(0.05)
        print(f"DAC {value:3d} -> ADC {esp.adc.read(34):4d} raw, {esp.adc.read_mv(34):4d} mV")

    esp.dac.cosine(25, 440)          # hardware 440 Hz tone generator
    time.sleep(3)
    esp.dac.disable(25)
