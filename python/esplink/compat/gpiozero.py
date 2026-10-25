"""gpiozero pin factory — LED, Button, PWMLED & friends on ESP32 pins.

    pip install gpiozero

    from gpiozero import LED, Button
    from esplink import Bridge
    from esplink.compat.gpiozero import EspLinkFactory

    esp = Bridge()
    factory = EspLinkFactory(esp)

    led = LED(2, pin_factory=factory)          # ESP32 GPIO numbers
    btn = Button(4, pin_factory=factory)
    btn.when_pressed = led.toggle

    # or make it the default for every gpiozero device:
    from gpiozero import Device
    Device.pin_factory = factory

Supported: input/output, pull-up/down, edge detection with debounce
(``when_pressed``/``when_changed``, run on a background thread so they may
drive other pins), PWM at any frequency (``PWMLED``, ``Servo``, ``Motor``),
and SPI devices (``MCP3008`` & co) on the ESP32's SPI host::

    adc = MCP3008(channel=0, pin_factory=factory)   # SCK 18, MOSI 23, MISO 19, CS 5
    adc = MCP3008(channel=0, select_pin=27, pin_factory=factory)
"""
from __future__ import annotations

import time

from gpiozero.exc import (PinInvalidFunction, PinInvalidPin, PinInvalidPull,
                          PinSetInput, SPIBadArgs)
from gpiozero.pins import SPI, BoardInfo, Factory, HeaderInfo, Pin, PinInfo

from ..pwm import pwm_bits
from .spidev import SpiDev

_EDGE_MAP = {"both": "change", "rising": "rising", "falling": "falling"}
_PULL_MODES = {"floating": "input", "up": "input_pullup", "down": "input_pulldown"}


def _board_info(gpio_count: int, chip: str) -> BoardInfo:
    pins = {
        n: PinInfo(number=n, name=f"GPIO{n}",
                   names=frozenset({n, str(n), f"GPIO{n}"}),
                   pull="", row=n + 1, col=1, interfaces=frozenset({"gpio"}))
        for n in range(gpio_count)
    }
    header = HeaderInfo(name="GPIO", rows=gpio_count, columns=1, pins=pins)
    return BoardInfo(
        revision="esplink", model=chip, pcb_revision="1.0", released="2026",
        soc=chip, manufacturer="Espressif", memory=0, storage="flash",
        usb=1, usb3=0, ethernet=0, eth_speed=0, wifi=True, bluetooth=True,
        csi=0, dsi=0, headers={"GPIO": header}, board="",
    )


class EspLinkPin(Pin):
    def __init__(self, factory: EspLinkFactory, info: PinInfo):
        super().__init__()
        self._factory = factory
        self._info = info
        self._gpio = factory._esp.gpio
        self._pwm = factory._esp.pwm
        self._n = info.number

        self._function = "input"
        self._pull = "floating"
        self._frequency: float | None = None
        self._duty = 0.0
        self._duty_max = 0
        self._bounce: float | None = None
        self._edges = "both"
        self._when_changed = None
        self._watching = False
        self._gpio.mode(self._n, "input")

    def __repr__(self):
        return f"<EspLinkPin GPIO{self._n}>"

    # ---- identity -------------------------------------------------------------
    def _get_info(self):
        return self._info

    # ---- function -------------------------------------------------------------
    def _get_function(self):
        return self._function

    def _set_function(self, value):
        if value not in ("input", "output"):
            raise PinInvalidFunction(f"invalid function {value!r} for {self!r}")
        self._function = value
        if value == "input":
            self._gpio.mode(self._n, _PULL_MODES[self._pull])
        else:
            self._gpio.mode(self._n, "output")

    def output_with_state(self, state):
        self._function = "output"
        self._gpio.mode(self._n, "output")
        self._set_state(state)

    def input_with_pull(self, pull):
        self._pull = pull
        self._set_function("input")

    # ---- state ------------------------------------------------------------------
    def _get_state(self):
        if self._frequency is not None:
            return self._duty
        return self._gpio.read(self._n)

    def _set_state(self, value):
        if self._frequency is not None:
            self._duty = max(0.0, min(1.0, float(value)))
            self._pwm.write(self._n, round(self._duty * self._duty_max))
        elif self._function == "input":
            raise PinSetInput(f"cannot set state of input {self!r}")
        else:
            self._gpio.write(self._n, bool(value))

    # ---- pull ---------------------------------------------------------------------
    def _get_pull(self):
        return self._pull

    def _set_pull(self, value):
        if value not in _PULL_MODES:
            raise PinInvalidPull(f"invalid pull {value!r} for {self!r}")
        self._pull = value
        if self._function == "input":
            self._gpio.mode(self._n, _PULL_MODES[value])

    # ---- PWM -----------------------------------------------------------------------
    def _get_frequency(self):
        return self._frequency

    def _set_frequency(self, value):
        if value is None:
            if self._frequency is not None:
                self._pwm.detach(self._n)
                self._frequency = None
                if self._function == "output":
                    self._gpio.mode(self._n, "output")
                    self._gpio.write(self._n, False)
        else:
            bits = pwm_bits(value)
            self._pwm.attach(self._n, int(value), bits)
            self._frequency, self._duty_max = float(value), (1 << bits) - 1
            self._pwm.write(self._n, round(self._duty * self._duty_max))

    # ---- edge detection ----------------------------------------------------------------
    def _get_bounce(self):
        return self._bounce

    def _set_bounce(self, value):
        self._bounce = value
        self._rearm()

    def _get_edges(self):
        return self._edges

    def _set_edges(self, value):
        if value not in ("both", "rising", "falling", "none"):
            raise PinInvalidFunction(f"invalid edges {value!r}")
        self._edges = value
        self._rearm()

    def _get_when_changed(self):
        return self._when_changed

    def _set_when_changed(self, value):
        self._when_changed = value
        self._rearm()

    def _rearm(self):
        if self._watching:
            self._gpio.unwatch(self._n)
            self._watching = False
        if self._when_changed is not None and self._edges != "none":
            debounce_ms = int((self._bounce or 0) * 1000)
            self._gpio.watch(self._n, _EDGE_MAP[self._edges],
                             debounce_ms=debounce_ms, callback=self._on_edge)
            self._watching = True

    def _on_edge(self, event):  # the Bridge's event thread: requests are fine here
        cb = self._when_changed
        if cb is not None:
            cb(self._factory.ticks(), event.level)

    def close(self):
        try:
            if self._watching:
                self._gpio.unwatch(self._n)
                self._watching = False
            if self._frequency is not None:
                self._pwm.detach(self._n)
                self._frequency = None
            self._gpio.mode(self._n, "input")
        except Exception:
            pass  # ignore errors: the bridge may already be closed, e.g. during interpreter shutdown
        self._function = "input"


class EspLinkFactory(Factory):
    """gpiozero pin factory backed by an esplink Bridge."""

    def __init__(self, esp):
        super().__init__()
        self._esp = esp
        self.pins: dict = {}
        gpio_count = esp.info.gpio_count if esp.info is not None else 40
        chip = esp.info.chip.name if esp.info is not None else "ESP32"
        self._board_info = _board_info(gpio_count, chip)

    def _get_board_info(self):
        return self._board_info

    @property
    def board_info(self):
        return self._board_info

    def _info(self, name) -> PinInfo:
        for _header, info in self.board_info.find_pin(name):
            return info
        raise PinInvalidPin(f"{name} is not a valid pin name")

    def pin(self, name):
        info = self._info(name)
        pin = self.pins.get(info)
        if pin is None:
            pin = EspLinkPin(self, info)
            self.pins[info] = pin
        return pin

    def spi(self, *, port=0, device=None, clock_pin=18, mosi_pin=23, miso_pin=19,
            select_pin=None, shared=False):
        """gpiozero's SPI arguments, with the ESP32's pins as defaults:
        ``device`` 0/1 means CS GPIO5/GPIO15, or name any ``select_pin``."""
        if device is not None and select_pin is not None:
            raise SPIBadArgs("give device or select_pin, not both")
        if select_pin is None:
            select_pin = (5, 15)[device or 0]
        pins = [None if p is None else self._info(p).number
                for p in (clock_pin, mosi_pin, miso_pin, select_pin)]
        return EspLinkSPI(self, port, *pins)

    def ticks(self):
        return time.monotonic()

    @staticmethod
    def ticks_diff(later, earlier):
        return later - earlier

    def close(self):
        for pin in list(self.pins.values()):
            pin.close()
        self.pins.clear()


class EspLinkSPI(SPI):
    """gpiozero SPI interface over esplink's spidev shim."""

    def __init__(self, factory, host, clock_pin, mosi_pin, miso_pin, select_pin):
        self._dev = None
        super().__init__(pin_factory=factory)
        self._cs = select_pin
        factory.reserve_pins(self, *(p for p in (clock_pin, mosi_pin, miso_pin, select_pin)
                                     if p is not None))
        self._dev = SpiDev(factory._esp, host, 0, sck=clock_pin, mosi=mosi_pin,
                           miso=miso_pin, ce=(select_pin,))

    def _conflicts_with(self, other):  # devices on one bus share SCK/MOSI/MISO
        return not (isinstance(other, EspLinkSPI) and other._cs != self._cs)

    @property
    def closed(self):
        return self._dev is None

    def close(self):
        if self._dev is not None:
            self._dev = None  # keep the host up: other devices may share it
            self.pin_factory.release_all(self)
        super().close()

    def __repr__(self):
        return f"SPI(select_pin={self._cs})" if self._dev else "SPI(closed)"

    def transfer(self, data):
        return self._dev.xfer2(data)

    def _get_clock_mode(self):
        return self._dev.mode

    def _set_clock_mode(self, value):
        self._dev.mode = value

    def _get_lsb_first(self):
        return self._dev.lsbfirst

    def _set_lsb_first(self, value):
        self._dev.lsbfirst = bool(value)

    def _get_bits_per_word(self):
        return self._dev.bits_per_word

    def _get_rate(self):
        return self._dev.max_speed_hz

    def _set_rate(self, value):
        self._dev.max_speed_hz = int(value)
