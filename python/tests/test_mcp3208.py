"""MCP3202/MCP3208 driver — decode verified against in-process chip emulators.

No hardware: a fake SPI backend answers exactly like the chip would, so the
command framing and 12-bit decode are exercised end to end.
"""
import pytest

from esplink.drivers.mcp3202 import MCP3202
from esplink.drivers.mcp3208 import MCP3208


class FakeSPI:
    """Emulates the ADC side of a full-duplex 3-byte SPI transfer."""

    def __init__(self, codes, two_ch):
        self.codes = codes      # channel -> 12-bit code the chip should report
        self.two_ch = two_ch    # MCP3202 frame instead of MCP3208
        self.last = None        # (channel, differential) decoded from the command

    def transfer(self, tx, *, cs=None, host=0):
        assert len(tx) == 3, "a read is always 3 bytes"
        if self.two_ch:
            assert tx[0] == 0x01, "byte0 must carry the start bit"
            single, ch = (tx[1] >> 7) & 1, (tx[1] >> 6) & 1
            assert (tx[1] >> 5) & 1, "MSBF must be set"
        else:
            single = (tx[0] >> 1) & 1
            ch = ((tx[0] & 1) << 2) | (tx[1] >> 6)   # D2 from byte0, D1D0 from byte1
        self.last = (ch, not single)
        code = self.codes.get(ch, 0) & 0x0FFF
        return bytes([0x00, code >> 8, code & 0xFF])


class FakeBridge:
    def __init__(self, spi):
        self.spi = spi


CHIPS = [(MCP3208, 8), (MCP3202, 2)]


def _adc(cls, codes):
    spi = FakeSPI(codes, cls is MCP3202)
    return cls(FakeBridge(spi), cs=5, vref=3.3), spi


@pytest.mark.parametrize("cls,n", CHIPS)
def test_channel_framing_and_decode(cls, n):
    adc, spi = _adc(cls, {c: c * 500 + 7 for c in range(n)})
    for ch in range(n):
        assert adc.read(ch) == ch * 500 + 7
        assert spi.last == (ch, False)


@pytest.mark.parametrize("cls,n", CHIPS)
def test_full_scale_voltage(cls, n):
    adc, _ = _adc(cls, {n - 1: 4095})
    assert abs(adc.read_voltage(n - 1) - 4095 / 4096 * 3.3) < 1e-9


@pytest.mark.parametrize("cls,n", CHIPS)
def test_differential_flag(cls, n):
    adc, spi = _adc(cls, {1: 42})
    assert adc.read(1, differential=True) == 42
    assert spi.last == (1, True)


@pytest.mark.parametrize("cls,n", CHIPS)
def test_channel_range(cls, n):
    adc, _ = _adc(cls, {})
    for bad in (-1, n):
        with pytest.raises(ValueError):
            adc.read(bad)
