"""Scan the I2C bus (SDA=21, SCL=22, the classic DevKit defaults).

    uv run basics/i2c_scan.py
"""
from esplink import Bridge

with Bridge() as esp:
    esp.i2c.init(sda=21, scl=22)
    print("devices:", [hex(a) for a in esp.i2c.scan()] or "none")
