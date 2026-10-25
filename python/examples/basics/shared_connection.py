"""esplink.connect(): one shared, thread-safe link for the whole program.

Every call with the same settings returns the SAME connection, so any thread,
web route or module can just ask for it instead of passing a Bridge around.
keepalive=5 pings every 5 s and reconnects after an unplug or reset.

    uv run basics/shared_connection.py
"""
import threading

import esplink


def worker(n):
    esp = esplink.connect(keepalive=5)       # same link as everyone else
    print(f"thread {n}: ADC34 = {esp.adc.read(34)}")


threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()
esplink.disconnect_all()
