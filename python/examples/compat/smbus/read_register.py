"""smbus2-style I2C — paste-compatible with classic Raspberry Pi code.

Scans the bus, then reads one register from the first device found
(0xD0 is the BME280 chip-id, harmless on most chips).

    uv run compat/smbus/read_register.py

Wiring: SDA -> GPIO21, SCL -> GPIO22.
"""
from esplink import Bridge
from esplink.compat.smbus import SMBus

REGISTER = 0xD0

with Bridge() as esp:
    bus = SMBus(esp)

    devices = esp.i2c.scan()
    if not devices:
        raise SystemExit("no I2C devices found — check wiring (SDA=GPIO21, "
                         "SCL=GPIO22) and power")
    print("devices on bus:", ", ".join(f"0x{a:02X}" for a in devices))

    addr = devices[0]
    value = bus.read_byte_data(addr, REGISTER)  # unchanged smbus2 API from here
    print(f"device 0x{addr:02X}, register 0x{REGISTER:02X} = 0x{value:02X}")
