"""Raspberry Pi API compatibility: the Pi's Python libraries, backed by an ESP32.

Per-library shims (import them directly, each takes the Bridge first)::

    esplink.compat.gpiozero   EspLinkFactory   gpiozero pin factory (LED, Button, MCP3008, ...)
    esplink.compat.rpi_gpio   module           RPi.GPIO / rpi-lgpio
    esplink.compat.smbus      SMBus, i2c_msg   smbus2 (and legacy smbus)
    esplink.compat.spidev     SpiDev           spidev
    esplink.compat.blinka     I2C, SPI, ...    Adafruit Blinka busio/digitalio
    esplink.compat.luma       LumaI2C/LumaSPI  luma.oled / luma.lcd interfaces

Or make an unmodified Pi script, *and the Pi libraries it imports*, run
against the ESP32::

    esplink.compat.install(Bridge())      # then: import RPi.GPIO, spidev, smbus2, gpiozero
    python -m esplink.compat my_pi_script.py [args]    # same, without editing the script

Pin numbers are always ESP32 GPIO numbers (BCM and BOARD mean the same thing).
"""
from __future__ import annotations

import sys
import types
from functools import partial


def install(esp) -> None:
    """Make ``import RPi.GPIO``, ``spidev``, ``smbus2``/``smbus`` resolve to
    this module's shims bound to ``esp``, and point gpiozero's default pin
    factory at it, so Pi scripts and third-party Pi libraries run unchanged."""
    from . import rpi_gpio, smbus, spidev

    rpi_gpio.attach(esp)
    rpi = types.ModuleType("RPi")
    rpi.GPIO = rpi_gpio
    mods = {"RPi": rpi, "RPi.GPIO": rpi_gpio}
    for name, attrs in (("spidev", {"SpiDev": partial(spidev.SpiDev, esp)}),
                        ("smbus2", {"SMBus": partial(smbus.SMBus, esp),
                                    "i2c_msg": smbus.i2c_msg}),
                        ("smbus", {"SMBus": partial(smbus.SMBus, esp)})):
        mods[name] = mod = types.ModuleType(name)
        vars(mod).update(attrs)
    sys.modules.update(mods)
    try:
        from gpiozero import Device
    except ImportError:
        return  # gpiozero is optional
    from .gpiozero import EspLinkFactory
    Device.pin_factory = EspLinkFactory(esp)
