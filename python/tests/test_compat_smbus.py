"""smbus2-compatible SMBus shim."""
import pytest

from esplink.compat.smbus import SMBus
from esplink.errors import RemoteError


@pytest.fixture()
def bus(bridge, fw):
    fw.i2c_devices[0x48] = bytes([0x1A, 0x80, 0x42, 0x43, 0x44])
    return SMBus(bridge)


def test_byte_ops(bus, fw):
    assert bus.read_byte(0x48) == 0x1A
    bus.write_byte(0x48, 0x55)
    assert fw.i2c_writes[-1] == (0x48, b"\x55")
    bus.write_quick(0x48)
    assert fw.i2c_writes[-1] == (0x48, b"")


def test_register_ops(bus, fw):
    assert bus.read_byte_data(0x48, 0x00) == 0x1A
    assert fw.i2c_writes[-1] == (0x48, b"\x00")  # read_byte_data first writes the register address, then reads

    bus.write_byte_data(0x48, 0x01, 0x60)
    assert fw.i2c_writes[-1] == (0x48, bytes([0x01, 0x60]))

    # SMBus words are little-endian
    assert bus.read_word_data(0x48, 0x00) == 0x801A
    bus.write_word_data(0x48, 0x02, 0xBEEF)
    assert fw.i2c_writes[-1] == (0x48, bytes([0x02, 0xEF, 0xBE]))


def test_block_ops(bus, fw):
    assert bus.read_i2c_block_data(0x48, 0x00, 5) == [0x1A, 0x80, 0x42, 0x43, 0x44]
    bus.write_i2c_block_data(0x48, 0x06, [1, 2, 3])
    assert fw.i2c_writes[-1] == (0x48, bytes([0x06, 1, 2, 3]))


def test_missing_device_raises(bus):
    with pytest.raises(RemoteError):
        bus.read_byte(0x21)


def test_pi_style_construction(bridge, fw):
    """SMBus(esp, 1): the Pi's bus number is accepted; context manager works."""
    fw.i2c_devices[0x48] = b"\x2a"
    with SMBus(bridge, 1) as bus:
        assert bus.read_byte(0x48) == 0x2A


def test_i2c_rdwr(bus, fw):
    from esplink.compat.smbus import i2c_msg

    w, r = i2c_msg.write(0x48, [0x00]), i2c_msg.read(0x48, 3)
    bus.i2c_rdwr(w, r)  # write + read of one device = one repeated-start transfer
    assert list(r) == [0x1A, 0x80, 0x42] and len(r) == 3 and r.buf[0] == 0x1A
    assert fw.i2c_writes[-1] == (0x48, b"\x00")

    bus.i2c_rdwr(i2c_msg.write(0x48, b"\x01\x02"))
    assert fw.i2c_writes[-1] == (0x48, b"\x01\x02")
    single = i2c_msg.read(0x48, 2)
    bus.i2c_rdwr(single)
    assert bytes(single) == b"\x1a\x80"
