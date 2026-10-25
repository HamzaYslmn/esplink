"""PWM via the ESP32 LEDC peripheral, plus servo/tone conveniences."""
from __future__ import annotations

import struct

from . import constants as C


def pwm_bits(freq: float) -> int:
    """Finest LEDC/nRF duty resolution that still fits ``freq``: the 16 MHz
    clock (the nRF's; the ESP's is 80) needs freq * 2**bits <= 16e6, capped at
    the 14 bits every chip supports — 14 at 50 Hz servos, 9 at 20 kHz motors."""
    return max(1, min(14, (16_000_000 // max(1, int(freq))).bit_length() - 1))


class Pwm:
    """PWM output via the LEDC peripheral, plus servo/tone helpers.

        esp.pwm.attach(2, freq=1000)
        esp.pwm.duty_pct(2, 50)        # 50% duty
        esp.pwm.detach(2)
    """

    def __init__(self, bridge):
        self._b = bridge
        self._attached: dict[int, tuple[int, int]] = {}  # pin -> (freq_hz, resolution_bits)

    def attach(self, pin: int, freq: int = 1000, resolution_bits: int | None = None) -> None:
        """Start a PWM channel on a pin at `freq` Hz. Resolution defaults to 10 bits
        (duty 0..1023): fewer when `freq` is too high for 10, more below ~76 Hz,
        where 10 bits would need an LEDC clock divider past its 1023 maximum."""
        if resolution_bits is None:
            resolution_bits = max((80_000_000 // 1023 // max(1, int(freq))).bit_length(),
                                  min(10, pwm_bits(freq)))
        self._b.request(C.PWM_ATTACH, struct.pack(">BIB", pin, freq, resolution_bits))
        self._attached[pin] = (freq, resolution_bits)

    def write(self, pin: int, duty: int) -> None:
        """Raw duty (0 .. 2**resolution_bits - 1)."""
        self._b.request(C.PWM_WRITE, struct.pack(">BI", pin, duty))

    def duty_pct(self, pin: int, percent: float) -> None:
        """Set duty cycle as a percentage (0..100); auto-attaches the pin if needed."""
        if pin not in self._attached:
            self.attach(pin)
        _, res = self._attached[pin]
        self.write(pin, round(((1 << res) - 1) * max(0.0, min(100.0, percent)) / 100.0))

    def detach(self, pin: int) -> None:
        """Stop PWM on a pin and free its LEDC channel."""
        self._b.request(C.PWM_DETACH, bytes([pin]))
        self._attached.pop(pin, None)

    def tone(self, pin: int, freq: int) -> None:
        """Square wave at `freq` Hz (0 = off) — buzzer-friendly."""
        self._b.request(C.PWM_TONE, struct.pack(">BI", pin, freq))

    def servo(self, pin: int, angle: float, *, min_us: int = 500, max_us: int = 2500) -> None:
        """Drive a hobby servo: 50 Hz, angle 0..180 mapped to min_us..max_us."""
        if self._attached.get(pin) != (50, 14):  # servo needs 50 Hz, 14-bit resolution
            self.attach(pin, 50, 14)
        us = min_us + (max_us - min_us) * max(0.0, min(180.0, angle)) / 180.0
        self.write(pin, round(us / 20000.0 * ((1 << 14) - 1)))
