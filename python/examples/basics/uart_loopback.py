"""Second UART for GPS modules, modems and other serial devices — pyserial-style.

Loopback test: jumper the board's UART TX to RX (esp.pins.tx -> esp.pins.rx;
GPIO 17 -> 16 on a classic ESP32). For a real device cross TX/RX and match the
baud (a GPS is usually 9600).

    uv run basics/uart_loopback.py
"""
from esplink import Bridge

with Bridge() as esp, esp.uart.init(baud=115_200) as port:
    port.timeout = 1
    port.write(b"hello, loopback!\n")
    print("got:", port.readline() or "nothing - is TX jumpered to RX?")
