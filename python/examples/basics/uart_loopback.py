"""Second UART for GPS modules, modems and other serial devices.

Loopback test: jumper GPIO 17 (TX) to GPIO 16 (RX). For a real device wire
its TX->16 / RX->17 and match the baud (a GPS is usually 9600).

    uv run basics/uart_loopback.py
"""
from esplink import Bridge

with Bridge() as esp:
    port = esp.uart.init(port=1, tx=17, rx=16, baud=115_200)
    port.write(b"hello, loopback!\n")
    print("got:", port.readline(timeout=1.0) or "nothing - is 17 jumpered to 16?")
    port.close()
