"""spidev-compatible SpiDev, so Raspberry Pi SPI code runs unchanged.

    from esplink import Bridge
    from esplink.compat.spidev import SpiDev

    esp = Bridge()
    spi = SpiDev(esp)                 # was: spidev.SpiDev()
    spi.open(0, 0)                    # SPI host 0, chip select CE0
    spi.max_speed_hz = 1_350_000
    raw = spi.xfer2([1, 0x80, 0])     # MCP3008 channel 0, identical from here

``open(bus, device)`` picks the ESP32 SPI host ``bus`` and the chip select
``ce[device]`` — CE0 is GPIO5 and CE1 is GPIO15 unless you pass ``ce=``, so
``open(0, 1)`` never lands on a strapping or UART pin. Clock, MOSI and MISO
default to the classic ESP32's VSPI pins 18/23/19.

Only 8-bit words with an active-low CS are supported. ``xfer`` holds CS for
the whole list like ``xfer2`` (spidev pulses it between words); per-call
``delay_usec`` is ignored.
"""
from __future__ import annotations

import weakref

from ..constants import MAX_PAYLOAD

_CHUNK = MAX_PAYLOAD - 2  # bytes one CS-framed transfer can carry (host + CS precede them)
_applied: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()  # esp.spi -> {host: settings}


class SpiDev:
    def __init__(self, esp, bus: int | None = None, device: int | None = None, *,
                 sck: int | None = None, mosi: int | None = None, miso: int | None = None,
                 ce=None):
        self._spi = esp.spi
        self._pins = {"sck": sck, "miso": miso, "mosi": mosi}
        self._ce = tuple(ce) if ce is not None else (esp.pins.cs, 15)  # CE0, CE1
        self._host = self._cs = None
        self.mode = 0
        self.max_speed_hz = 500_000  # what gpiozero sets on a Pi
        self.bits_per_word = 8
        self.lsbfirst = False
        self.cshigh = False
        self.no_cs = False
        if bus is not None:
            self.open(bus, device or 0)

    def open(self, bus: int, device: int) -> None:
        self._host, self._cs = bus, self._ce[device]
        self._sync(0)

    def close(self) -> None:
        if self._host is not None:
            self._spi.deinit(self._host)
            _applied.get(self._spi, {}).pop(self._host, None)
            self._host = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _sync(self, speed_hz: int) -> None:
        """(Re)configure the host only when settings changed — another SpiDev
        on the same host may have left it in a different mode or speed."""
        if self._host is None:
            raise OSError("SpiDev is not open; call open(bus, device) first")
        if self.bits_per_word != 8 or self.cshigh:
            raise ValueError("only 8-bit words with active-low chip select are supported")
        want = (self.mode, speed_hz or self.max_speed_hz, self.lsbfirst)
        hosts = _applied.setdefault(self._spi, {})
        if hosts.get(self._host) != want:
            self._spi.init(**self._pins, mode=want[0], freq=want[1],
                           msb_first=not want[2], host=self._host)
            hosts[self._host] = want

    def xfer2(self, values, speed_hz: int = 0, delay_usec: int = 0,
              bits_per_word: int = 0) -> list[int]:
        """Full-duplex transfer with CS held for the whole list."""
        self._sync(speed_hz)
        cs = None if self.no_cs else self._cs
        return list(self._spi.transfer(bytes(values), cs=cs, host=self._host))

    xfer = xfer2

    def xfer3(self, values, speed_hz: int = 0, delay_usec: int = 0,
              bits_per_word: int = 0) -> list[int]:
        """Like xfer2, for any length: CS is released between ~2 KB blocks."""
        data = bytes(values)
        out: list[int] = []
        for off in range(0, len(data), _CHUNK):
            out += self.xfer2(data[off : off + _CHUNK], speed_hz)
        return out

    def readbytes(self, n: int) -> list[int]:
        return self.xfer2(bytes(n))

    def writebytes(self, values) -> None:
        self.xfer2(values)

    def writebytes2(self, values) -> None:
        self.xfer3(values)
