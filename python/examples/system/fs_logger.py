"""Append a reading to a log file in the board's own flash (LittleFS), read it back.

    uv run system/fs_logger.py
"""
import time

from esplink import Bridge

with Bridge() as esp:
    vol = esp.fs.mount("littlefs")           # formats itself on first use
    vol.append_file("/sensor.log", f"{time.ctime()} adc={esp.adc.read(34)}\n".encode())
    print(vol.read_file("/sensor.log").decode(), end="")
    print(f"{vol.used_kb}/{vol.total_kb} KB used")
