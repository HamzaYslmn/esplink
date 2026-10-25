"""IR remote: print NEC codes from a TSOP receiver on GPIO 15. Ctrl+C stops.

To send instead: esp.ir_sender(pin=4).send_nec(addr, cmd), IR LED on GPIO 4.

    uv run devices/ir_remote.py
"""
from esplink import Bridge

with Bridge() as esp:
    rx = esp.ir_receiver(pin=15)
    print("point a remote at the receiver ...")
    try:
        while True:
            code = rx.receive(timeout_ms=10_000)   # (addr, cmd), "repeat" or None
            if isinstance(code, tuple):
                print(f"addr 0x{code[0]:02X}  cmd 0x{code[1]:02X}")
    except KeyboardInterrupt:
        pass
