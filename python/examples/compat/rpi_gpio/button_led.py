"""A plain Raspberry Pi RPi.GPIO script — not one line changed for the ESP32.

    uv run python -m esplink.compat compat/rpi_gpio/button_led.py

The runner connects to the board and makes ``import RPi.GPIO`` resolve to it.
(To use it from your own code instead: ``from esplink.compat import rpi_gpio
as GPIO`` and ``GPIO.attach(esp)``.)

Wiring: button GPIO4 -> GND (internal pull-up), LED on GPIO2 (on-board on
most DevKits), a second LED on GPIO5 breathes via hardware PWM.
"""
import time

import RPi.GPIO as GPIO

LED, BUTTON, DIMMED = 2, 4, 5

GPIO.setmode(GPIO.BCM)
GPIO.setup(LED, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(DIMMED, GPIO.OUT)


def pressed(channel):
    GPIO.output(LED, not GPIO.input(LED))
    print(f"GPIO{channel} pressed")


GPIO.add_event_detect(BUTTON, GPIO.FALLING, callback=pressed, bouncetime=50)
pwm = GPIO.PWM(DIMMED, 1000)
pwm.start(0)
print("press the button to toggle the LED — Ctrl+C to quit")
try:
    while True:
        for dc in (*range(0, 101, 5), *range(100, -1, -5)):
            pwm.ChangeDutyCycle(dc)
            time.sleep(0.05)
except KeyboardInterrupt:
    pass
finally:
    pwm.stop()
    GPIO.cleanup()
