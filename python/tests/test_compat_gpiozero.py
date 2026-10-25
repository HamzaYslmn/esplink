"""gpiozero pin factory: LED, Button (edge events), PWMLED via the bridge."""
import struct
import threading

import pytest

pytest.importorskip("gpiozero")
from gpiozero import LED, Button, PWMLED  # noqa: E402

from esplink import constants as C  # noqa: E402
from esplink.compat.gpiozero import EspLinkFactory  # noqa: E402


@pytest.fixture()
def factory(bridge):
    f = EspLinkFactory(bridge)
    yield f
    f.close()


def test_led_on_off_toggle(factory, fw):
    led = LED(2, pin_factory=factory)
    led.on()
    assert fw.gpio_modes[2] == 1 and fw.gpio_levels[2] == 1
    led.off()
    assert fw.gpio_levels[2] == 0
    led.toggle()
    assert fw.gpio_levels[2] == 1
    led.close()


def test_button_when_pressed_via_edge_event(factory, fw):
    fw.gpio_levels[4] = 1  # high = not pressed (active-low button with pull-up)
    btn = Button(4, pin_factory=factory)
    assert fw.gpio_modes[4] == 2          # mode 2 = input_pullup
    assert 4 in fw.watching               # pin 4 must have an edge-change watch registered
    assert not btn.is_pressed

    pressed = threading.Event()
    btn.when_pressed = lambda: pressed.set()

    fw.gpio_levels[4] = 0                 # update the fake hardware level so is_pressed is correct after the event fires
    fw.emit(C.GPIO_EDGE_EVT, bytes([4, 0]) + struct.pack(">I", 1234))
    assert pressed.wait(2.0)
    assert btn.is_pressed
    btn.close()
    assert 4 not in fw.watching


def test_pwmled_duty(factory, fw):
    led = PWMLED(5, pin_factory=factory)
    led.value = 0.5
    assert 5 in fw.pwm_attached
    assert fw.pwm_attached[5] == (100, 14)  # gpiozero's 100 Hz default: full 14 bits
    assert fw.pwm_duty[5] == round(0.5 * 16383)
    led.value = 1.0
    assert fw.pwm_duty[5] == 16383
    led.off()
    assert fw.pwm_duty[5] == 0
    led.close()


def test_pin_specs_and_identity(factory):
    p1 = factory.pin(2)
    p2 = factory.pin("GPIO2")
    p3 = factory.pin("2")
    assert p1 is p2 is p3


def test_when_pressed_can_drive_another_device(factory, fw):
    """The canonical `btn.when_pressed = led.toggle`: the callback makes a
    request, so it must not run on the reader thread that reads the reply."""
    fw.gpio_levels[4] = 1
    led, btn = LED(2, pin_factory=factory), Button(4, pin_factory=factory)
    done = threading.Event()
    btn.when_pressed = lambda: (led.toggle(), done.set())
    fw.gpio_levels[4] = 0
    fw.emit(C.GPIO_EDGE_EVT, bytes([4, 0]) + struct.pack(">I", 1))
    assert done.wait(1.0)  # was a 5 s timeout + "link lost" before
    assert fw.gpio_levels[2] == 1


def test_pwm_resolution_follows_frequency(factory, fw):
    led = PWMLED(5, frequency=25_000, pin_factory=factory)
    led.value = 1.0
    assert fw.pwm_attached[5] == (25_000, 9)
    assert fw.pwm_duty[5] == 511


def test_mcp3008_over_spi(factory, fw):
    from gpiozero import MCP3008
    from gpiozero.exc import GPIOPinInUse

    adc = MCP3008(channel=0, pin_factory=factory)  # ESP32 defaults: SCK18 MOSI23 MISO19 CS5
    adc.value
    assert fw.spi_transfers[-1] == bytes([0x01, 0x80, 0x00])  # start, single-ended ch0
    other = MCP3008(channel=1, device=1, pin_factory=factory)  # CS15 shares the bus
    assert repr(other._spi) == "SPI(select_pin=15)"
    with pytest.raises(GPIOPinInUse):
        LED(18, pin_factory=factory)  # SCK is taken
    adc.close()
    other.close()
    LED(18, pin_factory=factory).close()  # released again
