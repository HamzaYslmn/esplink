"""esp.pins: per-chip defaults that i2c/spi/uart.init() fill in when pins are omitted."""
import dataclasses
import struct

from esplink import constants as C


def _sent(bridge, call):
    """Run ``call`` and return the payloads it requested, by command."""
    sent, real = {}, bridge.request
    bridge.request = lambda cmd, payload=b"", **kw: (sent.setdefault(cmd, payload), real(cmd, payload, **kw))[1]
    try:
        call()
    finally:
        bridge.request = real
    return sent


def test_defaults_follow_the_chip(bridge):
    assert bridge.pins == C.PINS[C.ChipModel.ESP32]
    p = _sent(bridge, lambda: bridge.i2c.init())[C.I2C_INIT]
    assert struct.unpack(">BBBI", p)[1:3] == (21, 22)

    bridge.info = dataclasses.replace(bridge.info, chip=C.ChipModel.ESP32S3)
    assert bridge.pins.rgb == 48 and bridge.pins.led is None
    p = _sent(bridge, lambda: bridge.i2c.init())[C.I2C_INIT]
    assert struct.unpack(">BBBI", p)[1:3] == (8, 9)
    p = _sent(bridge, lambda: bridge.spi.init())[C.SPI_INIT]
    assert struct.unpack(">BbbbIBB", p)[1:4] == (12, 13, 11)


def test_explicit_pins_win(bridge):
    p = _sent(bridge, lambda: bridge.i2c.init(sda=1, scl=2))[C.I2C_INIT]
    assert struct.unpack(">BBBI", p)[1:3] == (1, 2)
