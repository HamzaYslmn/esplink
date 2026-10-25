"""MCP3202 / MCP3204 / MCP3208 — 12-bit, 2/4/8-channel SPI ADCs (Microchip).

A "bring your own" driver over the bridge's SPI primitive: single-ended (or
differential) single-shot reads, decoded to a 0..4095 code or to volts. No
firmware change needed. One class; ``channels`` picks the chip (8 = MCP3208,
4 = MCP3204, 2 = MCP3202, which also has a different command frame).

    from esplink import Bridge

    with Bridge() as esp:
        esp.spi.init(sck=18, miso=19, mosi=23, freq=1_000_000)
        adc = esp.mcp3208(cs=5, vref=3.3)          # esp.mcp3202(cs=5) for 2-ch
        code = adc.read(0)            # 0..4095 on CH0
        v    = adc.read_voltage(0)    # volts on CH0

Wiring: SPI mode 0. At a 3.3 V supply the clock ceiling is ~1 MHz for the
MCP3204/3208 and ~1.8 MHz for the MCP3202 — keep esp.spi.init(freq=) at or
below that or the low bits get noisy. VREF sets full scale; tie it to the
supply you measure against and pass the same value as `vref`.

Protocol (3 bytes, MSB-first; datasheets DS21298 / DS21034 sec. 6.1):
    MCP3204/3208: tx = [0x04 | SGL << 1 | ch >> 2, (ch & 3) << 6, 0x00]
    MCP3202:      tx = [0x01, SGL << 7 | ch << 6 | 0x20 (MSBF), 0x00]
    code = ((rx[1] & 0x0F) << 8) | rx[2]   # 12-bit result in the tail two bytes

Differential: `channel` selects a CH+/CH- pair (0 = CH0-CH1, 1 = CH1-CH0, ...).
"""
from __future__ import annotations


class MCP3208:
    def __init__(self, bridge, *, cs: int, vref: float = 3.3, host: int = 0,
                 channels: int = 8):
        if channels not in (2, 4, 8):
            raise ValueError(f"channels must be 2, 4 or 8, got {channels}")
        self._spi = bridge.spi
        self._cs = cs
        self._vref = vref
        self._host = host
        self._channels = channels

    def read(self, channel: int, *, differential: bool = False) -> int:
        """Sample one channel -> 12-bit code (0..4095)."""
        if not 0 <= channel < self._channels:
            raise ValueError(
                f"channel must be 0..{self._channels - 1}, got {channel}")
        sgl = 0 if differential else 1
        if self._channels == 2:
            tx = bytes([0x01, (sgl << 7) | (channel << 6) | 0x20, 0x00])
        else:
            tx = bytes([0x04 | (sgl << 1) | (channel >> 2), (channel & 3) << 6, 0x00])
        rx = self._spi.transfer(tx, cs=self._cs, host=self._host)
        return ((rx[1] & 0x0F) << 8) | rx[2]

    def read_voltage(self, channel: int, *, differential: bool = False) -> float:
        """Sample one channel -> volts (code / 4096 * vref)."""
        return self.read(channel, differential=differential) / 4096.0 * self._vref
