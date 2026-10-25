"""RPi.GPIO (and rpi-lgpio, its Pi 5 drop-in) on ESP32 pins.

    from esplink.compat import rpi_gpio as GPIO   # was: import RPi.GPIO as GPIO
    GPIO.attach(esp)        # optional: otherwise the first call opens Bridge()

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(2, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(4, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(4, GPIO.FALLING, callback=print, bouncetime=50)
    pwm = GPIO.PWM(5, 1000); pwm.start(25)
    GPIO.cleanup()

Same names, constants (values included), list arguments and millisecond
units as RPi.GPIO. Channel numbers are ESP32 GPIO numbers in both BCM and
BOARD mode — the ESP32 has no 40-pin header to count. PWM is the LEDC
hardware peripheral, not RPi.GPIO's jittery software PWM. Callbacks run in
order on one background thread, as on a Pi.
"""
from __future__ import annotations

import threading

from ..pwm import pwm_bits

BOARD, BCM = 10, 11
OUT, IN = 0, 1
LOW, HIGH = 0, 1
PUD_OFF, PUD_DOWN, PUD_UP = 20, 21, 22
RISING, FALLING, BOTH = 31, 32, 33
SERIAL, SPI, I2C, HARD_PWM, UNKNOWN = 40, 41, 42, 43, -1

_PULL = {PUD_OFF: "input", PUD_DOWN: "input_pulldown", PUD_UP: "input_pullup"}
_EDGE = {RISING: "rising", FALLING: "falling", BOTH: "change"}

_esp = None
_owned = False
_mode = None
_used: set[int] = set()              # channels setup() touched, for cleanup()
_detect: dict[int, list] = {}        # channel -> callbacks, for event-detected channels
_fired: set[int] = set()             # edges not yet collected by event_detected()
_pwm: set[int] = set()               # channels a started PWM drives


def attach(esp) -> None:
    """Drive this Bridge instead of opening one on first use."""
    global _esp, _owned
    _esp, _owned = esp, False


def _b():
    global _esp, _owned
    if _esp is None:
        from ..bridge import Bridge
        _esp, _owned = Bridge(), True
    return _esp


def _list(x) -> list:
    return list(x) if isinstance(x, (list, tuple)) else [x]


def setmode(mode) -> None:
    global _mode
    if _mode is not None and mode != _mode:
        raise ValueError("A different mode has already been set!")
    _mode = mode


def getmode():
    return _mode


def setwarnings(flag) -> None:
    pass  # nothing to warn about: no other process shares the ESP32's pins


def setup(channel, direction, pull_up_down=PUD_OFF, initial=None) -> None:
    gpio = _b().gpio
    for ch in _list(channel):
        _used.add(ch)
        if direction == OUT:
            gpio.mode(ch, "output")
            if initial is not None:
                gpio.write(ch, initial)
        else:
            gpio.mode(ch, _PULL[pull_up_down])


def output(channel, value) -> None:
    chans = _list(channel)
    vals = _list(value) if isinstance(value, (list, tuple)) else [value] * len(chans)
    if len(vals) != len(chans):
        raise RuntimeError("Number of channels != number of values")
    if len(chans) == 1:
        _b().gpio.write(chans[0], vals[0])
    else:
        _b().gpio.write_many(dict(zip(chans, vals)))


def input(channel) -> int:  # noqa: A001 — RPi.GPIO's name
    return _b().gpio.read(channel)


# ---- edge detection ----------------------------------------------------------
def _on_edge(ev) -> None:  # the Bridge's event thread, like RPi.GPIO's callback thread
    _fired.add(ev.pin)
    for cb in list(_detect.get(ev.pin, ())):
        cb(ev.pin)


def add_event_detect(channel, edge, callback=None, bouncetime=None) -> None:
    if channel in _detect:
        raise RuntimeError("Conflicting edge detection already enabled for this GPIO channel")
    _detect[channel] = [callback] if callback else []
    _b().gpio.watch(channel, _EDGE[edge], debounce_ms=int(bouncetime or 0),
                    callback=_on_edge)


def add_event_callback(channel, callback) -> None:
    if channel not in _detect:
        raise RuntimeError("Add event detection using add_event_detect first "
                           "before adding a callback")
    _detect[channel].append(callback)


def remove_event_detect(channel) -> None:
    if _detect.pop(channel, None) is not None:
        _b().gpio.unwatch(channel)
    _fired.discard(channel)


def event_detected(channel) -> bool:
    try:
        _fired.remove(channel)
        return True
    except KeyError:
        return False


def wait_for_edge(channel, edge, bouncetime=None, timeout=None):
    """Block until an edge; returns the channel, or None after ``timeout`` ms."""
    hit = threading.Event()
    add_event_detect(channel, edge, lambda _ch: hit.set(), bouncetime)
    try:
        return channel if hit.wait(None if timeout is None else timeout / 1000) else None
    finally:
        remove_event_detect(channel)


# ---- PWM ----------------------------------------------------------------------
class PWM:
    """RPi.GPIO.PWM, on the LEDC hardware PWM: duty cycle in percent."""

    def __init__(self, channel: int, frequency: float):
        self._ch, self._freq, self._dc = channel, frequency, 0.0
        self._on = False

    def start(self, dutycycle: float) -> None:
        _b().pwm.attach(self._ch, int(self._freq), pwm_bits(self._freq))
        self._on = True
        _used.add(self._ch)
        _pwm.add(self._ch)
        self.ChangeDutyCycle(dutycycle)

    def ChangeDutyCycle(self, dutycycle: float) -> None:
        if not 0.0 <= dutycycle <= 100.0:
            raise ValueError("dutycycle must have a value from 0.0 to 100.0")
        self._dc = dutycycle
        if self._on:
            _b().pwm.duty_pct(self._ch, dutycycle)

    def ChangeFrequency(self, frequency: float) -> None:
        if frequency <= 0.0:
            raise ValueError("frequency must be greater than 0.0")
        self._freq = frequency
        if self._on:
            self.start(self._dc)

    def stop(self) -> None:
        if self._on:
            self._on = False
            _pwm.discard(self._ch)
            _b().pwm.detach(self._ch)
            _b().gpio.mode(self._ch, "output")  # RPi.GPIO leaves the pin driven low
            _b().gpio.write(self._ch, 0)


def cleanup(chanlist=None) -> None:
    """Return channels (default: every one this script set up) to plain
    inputs; with no argument also forget the mode and close a Bridge this
    module opened itself."""
    global _esp, _owned, _mode
    if _esp is None:
        return
    chans = _used.copy() if chanlist is None else set(_list(chanlist))
    for ch in chans:
        remove_event_detect(ch)
        if ch in _pwm:
            _pwm.discard(ch)
            _esp.pwm.detach(ch)
        _esp.gpio.mode(ch, "input")
    _used.difference_update(chans)
    if chanlist is None:
        _mode = None
        if _owned:
            _esp.close()
            _esp, _owned = None, False
