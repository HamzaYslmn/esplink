"""PWM: fade an LED on GPIO 16, sweep a servo on GPIO 13, beep a buzzer on GPIO 27.

    uv run basics/pwm_servo.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    esp.pwm.attach(16, freq=5000)
    for pct in [*range(0, 101, 5), *range(100, -1, -5)]:
        esp.pwm.duty_pct(16, pct)
        time.sleep(0.03)

    for angle in (0, 90, 180, 90, 0):
        esp.pwm.servo(13, angle)
        time.sleep(0.7)

    for freq in (262, 330, 392, 523, 0):   # C E G C, 0 = off
        esp.pwm.tone(27, freq)
        time.sleep(0.2)
