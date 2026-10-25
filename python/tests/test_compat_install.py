"""esplink.compat.install(): unmodified Pi imports resolve to the ESP32."""
import contextlib
import sys

import pytest

import esplink.compat
from esplink.compat import __main__ as runner


@pytest.fixture()
def clean_modules():
    names = ("RPi", "RPi.GPIO", "spidev", "smbus2", "smbus")
    saved = {n: sys.modules.get(n) for n in names}
    yield
    for n, m in saved.items():
        if m is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = m
    from esplink.compat import rpi_gpio
    rpi_gpio.cleanup()


def test_pi_imports_resolve_to_bridge(bridge, fw, clean_modules):
    esplink.compat.install(bridge)
    import RPi.GPIO as GPIO
    import smbus2
    import spidev
    from gpiozero import LED, Device

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(2, GPIO.OUT)
    GPIO.output(2, GPIO.HIGH)
    assert fw.gpio_levels[2] == 1

    fw.i2c_devices[0x48] = b"\x07"
    assert smbus2.SMBus(1).read_byte_data(0x48, 0) == 7

    spi = spidev.SpiDev()
    spi.open(0, 0)
    assert spi.xfer2([0x9F]) == [0x9F]

    led = LED(13)  # default pin factory now the board
    led.on()
    assert fw.gpio_levels[13] == 1
    led.close()
    Device.pin_factory.close()
    Device.pin_factory = None


def test_run_unmodified_script(bridge, fw, clean_modules, monkeypatch, tmp_path):
    script = tmp_path / "blink.py"
    script.write_text(
        "import sys\n"
        "import RPi.GPIO as GPIO\n"
        "GPIO.setmode(GPIO.BCM)\n"
        "GPIO.setup(int(sys.argv[1]), GPIO.OUT, initial=GPIO.HIGH)\n")
    monkeypatch.setattr(runner, "Bridge", lambda name: contextlib.nullcontext(bridge))  # keep the fixture's link open
    monkeypatch.setattr(sys, "argv", sys.argv[:])
    runner.main([str(script), "12"])
    assert fw.gpio_modes[12] == 1 and fw.gpio_levels[12] == 1
    from gpiozero import Device
    Device.pin_factory = None
