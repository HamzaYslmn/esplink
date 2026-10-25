"""HC-SR04 ultrasonic distance: TRIG -> GPIO 5, ECHO -> GPIO 18.

The sensor runs at 5 V: divide ECHO down to 3.3 V (1k/2k divider).

    uv run devices/hcsr04_ping.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    sonar = esp.hcsr04(trig=5, echo=18)
    for _ in range(20):
        cm = sonar.distance_cm()
        print("out of range" if cm is None else f"{cm:.1f} cm")
        time.sleep(0.2)
