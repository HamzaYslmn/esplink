"""esplink.drivers.oled.OLED: dual-chip init, page-mode framing (SSD1306 +
SH1106) and changed-span updates, checked against a model of the panel's RAM."""
import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from esplink.drivers.oled import OLED  # noqa: E402


class FakeI2c:
    """Records writes and plays them into a 132-column page-mode RAM model."""
    max_write = 2046

    def __init__(self):
        self.inited = None
        self.writes = []   # (addr, data, wait)
        self.ram = [bytearray(132) for _ in range(8)]
        self.page = self.col = 0

    def init(self, *, sda=21, scl=22, freq=400_000, bus=0):
        self.inited = (sda, scl, freq, bus)

    def scan(self, bus=0):
        return [0x3C]

    def write(self, addr, data, bus=0, wait=True):
        assert len(data) <= self.max_write, "exceeds the Wire buffer"
        self.writes.append((addr, bytes(data), wait))
        i = 0
        while i < len(data):           # control byte: bit 7 Co, bit 6 D/C
            ctrl, i = data[i], i + 1
            run = data[i:i + 1] if ctrl & 0x80 else data[i:]
            i += len(run)
            for b in run:
                if ctrl & 0x40:        # display data: write + advance column
                    self.ram[self.page][self.col] = b
                    self.col += 1
                elif 0xB0 <= b <= 0xB7:
                    self.page = b - 0xB0
                # (init's multi-byte command parameters land in the column
                # branches too — harmless, show() always re-addresses first)
                elif b <= 0x0F:
                    self.col = (self.col & 0xF0) | b
                elif b <= 0x1F:
                    self.col = (self.col & 0x0F) | (b & 0x0F) << 4


class FakeEsp:
    def __init__(self):
        self.i2c = FakeI2c()


def _image(*pixels):
    img = Image.new("1", (128, 64))
    for xy in pixels:
        img.putpixel(xy, 1)
    return img


def _shown(i2c, colstart=0):
    return [bytes(p[colstart:colstart + 128]) for p in i2c.ram]


def _replay(img):
    """The RAM a fresh panel ends up with after a single full show(img)."""
    esp = FakeEsp()
    OLED(esp).show(img)
    return esp.i2c


def test_init_powers_both_chip_families_and_clears():
    esp = FakeEsp()
    esp.i2c.ram = [bytearray(b"\xa5" * 132) for _ in range(8)]  # power-on noise
    OLED(esp)
    assert esp.i2c.inited == (21, 22, 400_000, 0)
    assert all(w[0] == 0x3C for w in esp.i2c.writes)
    cmds = b"".join(w[1][1:] for w in esp.i2c.writes if w[1][0] == 0x00)
    assert bytes([0xAD, 0x8B]) in cmds   # SH1106 internal DC-DC on (harmless NOP on SSD1306)
    assert bytes([0x8D, 0x14]) in cmds   # SSD1306 charge-pump enable (harmless NOP on SH1106)
    assert esp.i2c.writes[-1][1] == b"\x00\xaf"  # display on — last, after RAM is cleared
    assert _shown(esp.i2c) == [bytes(128)] * 8


def _datas(i2c):
    return [d for _, d, _ in i2c.writes if d[0] == 0x40]


def test_show_addresses_then_writes_each_changed_page():
    esp = FakeEsp()
    oled = OLED(esp)
    esp.i2c.writes.clear()
    oled.show(_image((0, 0), (5, 9), (127, 63)))
    # per changed page: an address command, then a separate data write
    assert [w[1] for w in esp.i2c.writes] == [
        bytes([0x00, 0xB0, 0x00, 0x10]), bytes([0x40, 0x01]),  # page 0, column 0
        bytes([0x00, 0xB1, 0x05, 0x10]), bytes([0x40, 0x02]),  # page 1, column 5
        bytes([0x00, 0xB7, 0x0F, 0x17]), bytes([0x40, 0x80]),  # page 7, column 127
    ]
    pages = _shown(esp.i2c)
    # In page mode each byte encodes 8 vertical pixels; bit 0 is the topmost row.
    assert pages[0][0] == 0x01 and pages[1][5] == 0x02 and pages[7][127] == 0x80
    assert sum(b for p in pages for b in p) == 0x01 + 0x02 + 0x80


def test_only_the_changed_span_is_sent_and_the_last_write_waits():
    esp = FakeEsp()
    oled = OLED(esp)
    oled.show(_image((10, 0), (20, 0), (3, 30)))
    esp.i2c.writes.clear()
    oled.show(_image((10, 0), (20, 0), (3, 30)))
    assert esp.i2c.writes == []           # unchanged frame: no I/O at all

    img = _image((12, 0), (18, 0), (3, 30), (4, 40))
    oled.show(img)
    assert [len(d) - 1 for d in _datas(esp.i2c)] == [11, 1]  # columns 10..20, then one byte
    # pipelined: only the last write waits
    assert [wait for *_, wait in esp.i2c.writes] == [False] * 3 + [True]
    assert _shown(esp.i2c) == _shown(_replay(img))


def test_full_frame_change_is_eight_address_data_pairs():
    esp = FakeEsp()
    oled = OLED(esp)
    esp.i2c.writes.clear()
    oled.show(Image.new("1", (128, 64), 1))
    assert [wait for *_, wait in esp.i2c.writes] == [False] * 15 + [True]
    assert _shown(esp.i2c) == [b"\xff" * 128] * 8


def test_colstart_two_for_genuine_sh1106():
    # Many genuine SH1106 modules have a 132-column driver mapped to a 128-pixel
    # display, leaving a 2-column offset.  colstart=2 shifts addressing accordingly.
    esp = FakeEsp()
    oled = OLED(esp, colstart=2)
    oled.show(_image((0, 0), (127, 0)))
    assert esp.i2c.ram[0][2] == 0x01 and esp.i2c.ram[0][129] == 0x01


def test_colstart_change_repaints_everything():
    esp = FakeEsp()
    oled = OLED(esp)            # colstart 0
    img = _image((0, 0), (64, 32))
    oled.show(img)
    oled.colstart = 2           # e.g. after discovering the panel is a 1.3" SH1106
    esp.i2c.writes.clear()
    oled.show(img)              # same image, new window: must still be sent
    assert len(esp.i2c.writes) == 16
    assert _shown(esp.i2c, colstart=2) == _shown(_replay(img))


def test_horizontal_flip_repaints_on_next_show():
    esp = FakeEsp()
    oled = OLED(esp)
    img = _image((1, 1))
    oled.show(img)
    oled.flip(horizontal=True)  # remaps RAM writes: the old RAM is now mirrored
    esp.i2c.writes.clear()
    oled.show(img)
    assert len(esp.i2c.writes) == 16


def test_failed_frame_repaints_on_next_show():
    esp = FakeEsp()
    oled = OLED(esp)
    real_write = esp.i2c.write

    def flaky(addr, data, bus=0, wait=True):
        real_write(addr, data, bus, wait)
        if wait:
            raise TimeoutError("link dropped")
    esp.i2c.write = flaky
    with pytest.raises(TimeoutError):
        oled.show(_image((0, 0)))
    esp.i2c.write = real_write
    esp.i2c.writes.clear()
    oled.show(_image((0, 0)))   # unknown panel state: sent again, in full
    assert len(esp.i2c.writes) == 16


def test_split_spans_readdress_each_chunk():
    """A heap-squeezed firmware Wire buffer (128 B) can't take a full 128-byte
    page per write; every chunk must re-set page + column explicitly because
    clones disagree on column-pointer behavior across transactions."""
    esp = FakeEsp()
    esp.i2c.max_write = 126     # what a 128 B Wire buffer yields
    oled = OLED(esp, colstart=2)
    esp.i2c.writes.clear()
    img = Image.new("1", (128, 64), 1)  # every page changes in full
    oled.show(img)
    assert [len(d) - 1 for d in _datas(esp.i2c)] == [125, 3] * 8
    # second chunk of page 0 starts at column 125 + colstart 2 = 127 = 0x7F
    assert esp.i2c.writes[2][1] == bytes([0x00, 0xB0, 0x0F, 0x17])
    assert _shown(esp.i2c, colstart=2) == _shown(_replay(img))


def test_draw_context_manager_pushes_frame():
    esp = FakeEsp()
    oled = OLED(esp)
    with oled.draw() as d:
        d.rectangle((0, 0, 127, 63), fill="white")
    assert _shown(esp.i2c) == [b"\xff" * 128] * 8  # fully lit


def test_clear_rewrites_all_ram():
    esp = FakeEsp()
    oled = OLED(esp)
    esp.i2c.ram[3][40] = 0xFF   # RAM changed behind the driver's back
    oled.clear()
    assert _shown(esp.i2c) == [bytes(128)] * 8


def test_named_panel_controls():
    esp = FakeEsp()
    oled = OLED(esp)
    esp.i2c.writes.clear()

    oled.contrast(0xFF)
    oled.invert()
    oled.vertical_offset(2)
    oled.start_line(8)
    oled.flip(horizontal=True, vertical=True)   # 180 degrees
    oled.power(False)

    sent = [w[1][1:] for w in esp.i2c.writes]
    assert sent == [
        bytes([0x81, 0xFF]),
        bytes([0xA7]),
        bytes([0xD3, 0x02]),
        bytes([0x40 | 0x08]),
        bytes([0xA0, 0xC0]),
        bytes([0xAE]),
    ]
