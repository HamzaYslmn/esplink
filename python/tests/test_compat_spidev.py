"""spidev-compatible SpiDev over the fake firmware (whose SPI loops tx back as rx)."""
import pytest

from esplink.compat.spidev import SpiDev


@pytest.fixture()
def inits(bridge, monkeypatch):
    calls = []
    real = bridge.spi.init
    monkeypatch.setattr(bridge.spi, "init", lambda **kw: (calls.append(kw), real(**kw)))
    return calls


def test_open_xfer_and_settings(bridge, fw, inits):
    spi = SpiDev(bridge)
    with pytest.raises(OSError):
        spi.xfer2([1])  # not open yet, like spidev
    spi.open(0, 0)
    spi.max_speed_hz = 1_350_000
    spi.mode = 0b11
    assert spi.xfer2([1, 0x80, 0]) == [1, 0x80, 0]
    assert inits[-1] == {"sck": 18, "miso": 19, "mosi": 23, "mode": 3,
                         "freq": 1_350_000, "msb_first": True, "host": 0}
    n = len(inits)
    spi.xfer([0xAA])
    spi.writebytes([1, 2])
    assert spi.readbytes(3) == [0, 0, 0]
    assert len(inits) == n  # unchanged settings: no re-init per transfer
    spi.xfer2([0], 2_000_000)
    assert inits[-1]["freq"] == 2_000_000  # per-call speed_hz
    assert fw.spi_transfers[-1] == b"\x00"
    spi.close()
    assert not fw.spi_inited


def test_ce_maps_device_to_cs_pin(bridge, monkeypatch):
    cs = []
    real = bridge.spi.transfer
    monkeypatch.setattr(bridge.spi, "transfer",
                        lambda tx, **kw: (cs.append(kw["cs"]), real(tx, **kw))[1])
    SpiDev(bridge, 0, 1).xfer2([0])
    SpiDev(bridge, 0, 0, ce=(27,)).xfer2([0])
    nocs = SpiDev(bridge, 0, 0)
    nocs.no_cs = True
    nocs.xfer2([0])
    assert cs == [15, 27, None]


def test_two_devices_on_one_host_resync(bridge, inits):
    a, b = SpiDev(bridge, 0, 0), SpiDev(bridge, 0, 1)
    b.mode = 1
    b.xfer2([0])
    a.xfer2([0])  # a must restore mode 0 that b changed
    assert [c["mode"] for c in inits] == [0, 1, 0]


def test_xfer3_and_writebytes2_split_large_buffers(bridge, fw):
    spi = SpiDev(bridge, 0, 0)
    data = bytes(range(256)) * 20  # 5120 bytes, more than one CS frame
    assert spi.xfer3(data) == list(data)
    spi.writebytes2(bytearray(data))
    assert b"".join(fw.spi_transfers[-3:]) == data


def test_unsupported_settings_raise(bridge):
    spi = SpiDev(bridge, 0, 0)
    spi.bits_per_word = 16
    with pytest.raises(ValueError):
        spi.xfer2([0])
