"""Write your own device driver: a plain class whose first argument is the Bridge.

No firmware change: the driver speaks the device's protocol over the bridge's
primitives (here I2C). Example device: an LM75/TMP102 thermometer at 0x48.
Full guide, including shipping a driver as a pip plugin: docs/DRIVERS.md.

    uv run devices/custom_driver.py
"""
from esplink import Bridge, register_driver


class LM75:
    def __init__(self, bridge, address=0x48):
        self.i2c, self.address = bridge.i2c, address

    def read_c(self):
        raw = int.from_bytes(self.i2c.read_reg(self.address, 0x00, 2), "big", signed=True)
        return (raw >> 4) * 0.0625           # 12-bit, 1/16 degC per step


register_driver("lm75", LM75)                # optional: enables esp.lm75()

with Bridge() as esp:
    esp.i2c.init(sda=21, scl=22)
    print(f"{esp.lm75().read_c():.2f} C")
