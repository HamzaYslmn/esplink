"""SPI: read the JEDEC ID of a SPI flash chip (W25Qxx etc.), CS on GPIO 5.

    uv run basics/spi_transfer.py
"""
from esplink import Bridge

with Bridge() as esp:
    esp.spi.init(sck=18, miso=19, mosi=23, freq=1_000_000)
    rx = esp.spi.transfer(bytes([0x9F, 0, 0, 0]), cs=5)   # 0x9F = Read JEDEC ID
    print(f"manufacturer 0x{rx[1]:02X}, type 0x{rx[2]:02X}, capacity 0x{rx[3]:02X}")
