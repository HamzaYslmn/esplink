"""RPi.GPIO-compatible module over the fake firmware."""
import struct

import pytest

from esplink import constants as C
from esplink.compat import rpi_gpio as GPIO


@pytest.fixture()
def gpio(bridge):
    GPIO.attach(bridge)
    yield GPIO
    GPIO.cleanup()


def edge(fw, pin, level):
    fw.gpio_levels[pin] = level
    fw.emit(C.GPIO_EDGE_EVT, bytes([pin, level]) + struct.pack(">I", 1))


def test_setmode_and_constants_match_rpi_gpio(gpio):
    assert (GPIO.BOARD, GPIO.BCM, GPIO.OUT, GPIO.IN) == (10, 11, 0, 1)
    assert (GPIO.PUD_OFF, GPIO.PUD_DOWN, GPIO.PUD_UP) == (20, 21, 22)
    assert (GPIO.RISING, GPIO.FALLING, GPIO.BOTH) == (31, 32, 33)
    assert GPIO.getmode() is None
    GPIO.setmode(GPIO.BCM)
    GPIO.setmode(GPIO.BCM)  # same mode again is fine
    with pytest.raises(ValueError):
        GPIO.setmode(GPIO.BOARD)
    GPIO.cleanup()
    assert GPIO.getmode() is None


def test_setup_output_input(gpio, fw):
    GPIO.setup(2, GPIO.OUT, initial=GPIO.HIGH)
    assert fw.gpio_modes[2] == 1 and fw.gpio_levels[2] == 1
    GPIO.output(2, GPIO.LOW)
    assert fw.gpio_levels[2] == 0

    GPIO.setup([12, 13], GPIO.OUT)
    GPIO.output([12, 13], [1, 0])
    assert (fw.gpio_levels[12], fw.gpio_levels[13]) == (1, 0)
    GPIO.output((12, 13), GPIO.HIGH)
    assert (fw.gpio_levels[12], fw.gpio_levels[13]) == (1, 1)
    with pytest.raises(RuntimeError):
        GPIO.output([12, 13], [1])

    GPIO.setup(4, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    assert fw.gpio_modes[4] == 2
    fw.gpio_levels[4] = 1
    assert GPIO.input(4) == GPIO.HIGH

    GPIO.cleanup(2)
    assert fw.gpio_modes[2] == 0  # back to a plain input
    GPIO.cleanup()
    assert fw.gpio_modes[12] == fw.gpio_modes[4] == 0


def test_event_detect_callback_may_drive_pins(gpio, fw):
    """The callback runs off the reader thread, so it can make requests."""
    import threading

    GPIO.setup(2, GPIO.OUT)
    GPIO.setup(4, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    seen, done = [], threading.Event()

    def cb(ch):
        seen.append(ch)
        GPIO.output(2, GPIO.HIGH)  # would deadlock on the reader thread
        done.set()

    GPIO.add_event_detect(4, GPIO.FALLING, callback=cb, bouncetime=50)
    assert fw.watching[4] == (2, 50)  # falling edge, 50 ms debounce
    with pytest.raises(RuntimeError):
        GPIO.add_event_detect(4, GPIO.RISING)
    edge(fw, 4, 0)
    assert done.wait(2.0)
    assert seen == [4] and fw.gpio_levels[2] == 1
    assert GPIO.event_detected(4) and not GPIO.event_detected(4)

    GPIO.remove_event_detect(4)
    assert 4 not in fw.watching


def test_add_event_callback_needs_detect(gpio):
    with pytest.raises(RuntimeError):
        GPIO.add_event_callback(4, print)


def test_wait_for_edge(gpio, fw):
    import threading

    GPIO.setup(4, GPIO.IN)
    assert GPIO.wait_for_edge(4, GPIO.RISING, timeout=20) is None  # ms, like RPi.GPIO
    threading.Timer(0.05, edge, (fw, 4, 1)).start()
    assert GPIO.wait_for_edge(4, GPIO.RISING, timeout=2000) == 4
    assert 4 not in fw.watching


def test_pwm(gpio, fw):
    GPIO.setup(5, GPIO.OUT)
    p = GPIO.PWM(5, 50)
    p.start(50)
    assert fw.pwm_attached[5] == (50, 14)
    assert fw.pwm_duty[5] == round(0.5 * (2**14 - 1))
    p.ChangeFrequency(20_000)  # resolution drops so 20 kHz still fits the clock
    assert fw.pwm_attached[5] == (20_000, 9)
    assert fw.pwm_duty[5] == round(0.5 * 511)
    with pytest.raises(ValueError):
        p.ChangeDutyCycle(101)
    p.stop()
    assert 5 not in fw.pwm_attached and fw.gpio_levels[5] == 0
    p.start(10)
    GPIO.cleanup()
    assert 5 not in fw.pwm_attached
