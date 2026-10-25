"""gpiozero's MCP3008 + PWMLED recipe: a potentiometer dims an LED.

    uv run gpiozero/pot_dimmer.py

``led.source = pot`` streams the ADC into the LED on a background thread,
exactly as on a Raspberry Pi; only the pin factory line is new.

Wiring: MCP3008 CLK -> GPIO18, DOUT -> GPIO19, DIN -> GPIO23, CS -> GPIO5,
potentiometer on CH0; LED (+ resistor) on GPIO2.
"""
import time

from gpiozero import MCP3008, PWMLED, Device

from esplink import Bridge
from esplink.compat.gpiozero import EspLinkFactory

with Bridge() as esp:
    Device.pin_factory = EspLinkFactory(esp)
    pot = MCP3008(channel=0)        # SPI host 0, CS GPIO5
    led = PWMLED(2)
    led.source = pot
    print("turn the potentiometer — Ctrl+C to quit")
    try:
        while True:
            print(f"pot {pot.value:.2f}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        led.close()
        pot.close()
        Device.pin_factory.close()
