"""Stepper via an A4988/DRV8825 driver: STEP -> GPIO 12, DIR -> GPIO 14.

    uv run devices/stepper_move.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    motor = esp.stepper(step_pin=12, dir_pin=14)
    motor.move(200, speed=800, accel=1600)   # one revolution (1.8 deg/step), ramped
    motor.move(-200, speed=400)              # and back, constant speed
    motor.run(600)                           # free-run at 600 steps/s ...
    time.sleep(3)
    motor.stop()
