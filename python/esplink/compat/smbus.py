"""smbus2-compatible SMBus (also covers legacy python-smbus), so Raspberry Pi
I2C code runs unchanged.

    from esplink import Bridge
    from esplink.compat.smbus import SMBus, i2c_msg

    with Bridge() as esp, SMBus(esp, 1) as bus:   # was: SMBus(1)
        temp = bus.read_byte_data(0x48, 0x00)     # the rest of the code is identical
        bus.write_i2c_block_data(0x20, 0x06, [0xFF, 0x00])
        w, r = i2c_msg.write(0x44, [0x24, 0x00]), i2c_msg.read(0x44, 6)
        bus.i2c_rdwr(w, r)                        # repeated start; data in list(r)

The bus number (``/dev/i2c-N`` on a Pi) is accepted and ignored: the ESP32
I2C controller is ``i2c_bus`` (default 0) on pins ``sda``/``scl``. Pass
``init=False`` to share a bus already set up with ``esp.i2c.init()``.
Word data is little-endian, matching the SMBus specification (and smbus2).
"""
from __future__ import annotations


class i2c_msg:  # noqa: N801 — smbus2's name
    """One message of an :meth:`SMBus.i2c_rdwr` transaction."""

    def __init__(self, addr: int, buf, is_read: bool):
        self.addr, self.buf, self.len, self.flags = addr, bytearray(buf), len(buf), int(is_read)

    @classmethod
    def read(cls, address: int, length: int) -> i2c_msg:
        return cls(address, bytes(length), True)

    @classmethod
    def write(cls, address: int, buf) -> i2c_msg:
        return cls(address, buf.encode() if isinstance(buf, str) else bytes(buf), False)

    def __iter__(self):
        return iter(self.buf)

    def __len__(self) -> int:
        return self.len

    def __bytes__(self) -> bytes:
        return bytes(self.buf)


class SMBus:
    def __init__(self, esp, bus=None, force: bool = False, *, sda: int | None = None,
                 scl: int | None = None, freq: int = 100_000, i2c_bus: int = 0, init: bool = True):
        self._i2c = esp.i2c
        self._bus = i2c_bus
        self._pins = {"sda": sda, "scl": scl, "freq": freq}
        if init:
            self.open(bus)

    def open(self, bus=None) -> None:
        self._i2c.init(bus=self._bus, **self._pins)

    # ---- plain byte ----------------------------------------------------------
    def read_byte(self, i2c_addr: int, force=None) -> int:
        return self._i2c.read(i2c_addr, 1, self._bus)[0]

    def write_byte(self, i2c_addr: int, value: int, force=None) -> None:
        self._i2c.write(i2c_addr, bytes([value & 0xFF]), self._bus)

    def write_quick(self, i2c_addr: int, force=None) -> None:
        self._i2c.write(i2c_addr, b"", self._bus)

    # ---- register (command) based -----------------------------------------------
    def read_byte_data(self, i2c_addr: int, register: int, force=None) -> int:
        return self._i2c.write_read(i2c_addr, bytes([register]), 1, self._bus)[0]

    def write_byte_data(self, i2c_addr: int, register: int, value: int, force=None) -> None:
        self._i2c.write(i2c_addr, bytes([register, value & 0xFF]), self._bus)

    def read_word_data(self, i2c_addr: int, register: int, force=None) -> int:
        lo, hi = self._i2c.write_read(i2c_addr, bytes([register]), 2, self._bus)
        return lo | (hi << 8)

    def write_word_data(self, i2c_addr: int, register: int, value: int, force=None) -> None:
        self._i2c.write(i2c_addr, bytes([register, value & 0xFF, (value >> 8) & 0xFF]),
                        self._bus)

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int = 32,
                            force=None) -> list[int]:
        return list(self._i2c.write_read(i2c_addr, bytes([register]), length, self._bus))

    def write_i2c_block_data(self, i2c_addr: int, register: int, data, force=None) -> None:
        self._i2c.write(i2c_addr, bytes([register]) + bytes(data), self._bus)

    # ---- raw I2C transactions -----------------------------------------------------
    def i2c_rdwr(self, *msgs: i2c_msg) -> None:
        """Run the messages in order; a write followed by a read of the same
        device is one write-then-read with a repeated start (the common
        register read). Read data lands in each read message."""
        i = 0
        while i < len(msgs):
            m = msgs[i]
            nxt = msgs[i + 1] if i + 1 < len(msgs) else None
            if not m.flags and nxt is not None and nxt.flags and nxt.addr == m.addr:
                nxt.buf[:] = self._i2c.write_read(m.addr, bytes(m.buf), nxt.len, self._bus)
                i += 2
                continue
            if m.flags:
                m.buf[:] = self._i2c.read(m.addr, m.len, self._bus)
            else:
                self._i2c.write(m.addr, bytes(m.buf), self._bus)
            i += 1

    # ---- lifecycle -------------------------------------------------------------
    def close(self) -> None:
        pass  # the Bridge owns the link and the bus

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
