"""esplink flash: the board is picked from the USB ID, and the Pro Micro is flashed by
copying its UF2 onto the bootloader drive the 1200-baud touch mounts."""
import contextlib
import sys
from types import SimpleNamespace

import serial
from serial.tools import list_ports

from esplink import flash


def test_board_follows_the_usb_vendor(monkeypatch):
    ports = [SimpleNamespace(device="A", vid=0x303A), SimpleNamespace(device="B", vid=0x239A),
             SimpleNamespace(device="C", vid=0x10C4)]
    monkeypatch.setattr(list_ports, "comports", lambda: ports)
    monkeypatch.setitem(sys.modules, "esptool", None)  # no esptool: a bridge port falls back to esp32
    assert [flash.detect_chip(p) for p in "ABCD"] == ["esp32s3", "promicro", "esp32", "esp32"]


def test_behind_a_usb_uart_bridge_the_chip_is_asked(monkeypatch):
    monkeypatch.setattr(list_ports, "comports", lambda: [SimpleNamespace(device="C", vid=0x1A86)])
    chip = SimpleNamespace(CHIP_NAME="ESP32-S3")
    fake = SimpleNamespace(detect_chip=lambda port: contextlib.nullcontext(chip))
    monkeypatch.setitem(sys.modules, "esptool", fake)
    assert flash.detect_chip("C") == "esp32s3"   # an S3 on its UART port gets the S3 image


def test_uf2_lands_on_the_drive_the_touch_mounts(monkeypatch, tmp_path):
    drive, fw = tmp_path / "drive", tmp_path / "bridge.promicro.uf2"
    drive.mkdir()
    fw.write_bytes(b"UF2\n" + bytes(508))
    touched = []

    class Touch:  # opening at 1200 baud is what reboots the app into the bootloader
        def __init__(self, port, baud):
            touched.append((port, baud))
            (drive / "INFO_UF2.TXT").write_text("UF2 Bootloader")

        def close(self):
            pass

    monkeypatch.setattr(serial, "Serial", Touch)
    monkeypatch.setattr(flash, "_uf2_drives",
                        lambda: [drive] if (drive / "INFO_UF2.TXT").exists() else [])
    flash.flash_firmware("COM9", firmware=fw, chip="promicro")
    assert touched == [("COM9", 1200)]
    assert (drive / fw.name).read_bytes() == fw.read_bytes()
