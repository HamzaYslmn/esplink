"""A run counter kept in the ESP32's NVS flash: it survives resets and power-offs.

    uv run system/nvs_counter.py
"""
from esplink import Bridge

with Bridge() as esp:
    runs = esp.nvs.get_int("runs", 0) + 1
    esp.nvs.set("runs", runs)
    print(f"run #{runs} on this board; keys: {esp.nvs.keys()}")
