"""Secondary UARTs (1, 2): write from host, RX streamed back as events."""
from __future__ import annotations

import struct
import threading
import time

from . import constants as C

# Maximum bytes sent in a single UART_WRITE request. Keeping this bounded
# limits how long the firmware's synchronous write can block on a slow baud rate.
_WRITE_CHUNK = 1024


class UartPort:
    """Bridged UART that behaves like a pyserial ``Serial``: ``read(size)`` waits
    for ``size`` bytes or ``timeout``, ``write()`` returns the count, iterate it
    for lines, use it in ``with``. RX arrives as events, buffered here."""

    def __init__(self, bridge, port: int, baudrate: int = 115_200):
        self._b = bridge
        self.port = port
        self.baudrate = baudrate
        self.timeout: float | None = None  # pyserial: None waits forever, 0 never
        self.is_open = True
        self._buf = bytearray()
        self._cond = threading.Condition()
        self._callbacks: list = []

    def _feed(self, data: bytes) -> None:
        with self._cond:
            self._buf += data
            self._cond.notify_all()
        for cb in list(self._callbacks):
            cb(data)

    def write(self, data: bytes) -> int:
        """Send bytes out the port (chunked into <= 1 KB requests); returns the count."""
        data = bytes(data)
        for off in range(0, len(data), _WRITE_CHUNK):
            self._b.request(C.UART_WRITE, bytes([self.port]) + data[off : off + _WRITE_CHUNK])
        return len(data)

    def _take(self, n: int) -> bytes:
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    def _wait(self, ready, timeout: float | None) -> None:
        """Wait (holding the lock) until ready() or the timeout, pyserial-style."""
        timeout = self.timeout if timeout is None else timeout
        deadline = None if timeout is None else time.monotonic() + timeout
        while not ready():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return
            self._cond.wait(remaining)

    def read(self, size: int = 1, *, timeout: float | None = None) -> bytes:
        """Read ``size`` bytes, returning fewer only if the timeout passes."""
        with self._cond:
            self._wait(lambda: len(self._buf) >= size, timeout)
            return self._take(size)

    def read_all(self) -> bytes:
        """Everything already received, without waiting."""
        with self._cond:
            return self._take(len(self._buf))

    def read_until(self, expected: bytes = b"\n", size: int | None = None, *,
                   timeout: float | None = None) -> bytes:
        """Read through ``expected`` (or ``size`` bytes); on timeout, what arrived."""
        def found():
            return expected in self._buf or (size is not None and len(self._buf) >= size)
        with self._cond:
            self._wait(found, timeout)
            i = self._buf.find(expected)
            n = len(self._buf) if i < 0 else i + len(expected)
            return self._take(n if size is None else min(n, size))

    def readline(self, size: int = -1, *, timeout: float | None = None) -> bytes:
        return self.read_until(b"\n", None if size < 0 else size, timeout=timeout)

    def readlines(self) -> list[bytes]:
        """Lines until a read times out (set ``timeout``, or this never ends)."""
        return list(self)

    def __iter__(self):
        while line := self.readline():
            yield line

    @property
    def in_waiting(self) -> int:
        """Bytes already received and buffered."""
        with self._cond:
            return len(self._buf)

    def reset_input_buffer(self) -> None:
        """Discard all buffered received bytes."""
        with self._cond:
            self._buf.clear()

    def flush(self) -> None:
        """No-op: writes are synchronous requests."""

    def on_rx(self, callback) -> None:
        """callback(bytes) on every RX chunk (on the Bridge's event thread)."""
        self._callbacks.append(callback)

    def close(self) -> None:
        """Tear down the port on the firmware (stops RX streaming)."""
        if self.is_open:
            self._b.request(C.UART_DEINIT, bytes([self.port]))
            self.is_open = False

    def __enter__(self) -> UartPort:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class Uart:
    """Secondary UART manager; init() returns a pyserial-like UartPort.

        port = esp.uart.init(port=1, tx=17, rx=16, baud=9600)
        port.write(b"AT\\r\\n")
        print(port.readline())
    """

    def __init__(self, bridge):
        self._b = bridge
        self._ports: dict[int, UartPort] = {}
        bridge.on_event(C.UART_RX_EVT, self._on_rx)

    def _on_rx(self, payload: bytes) -> None:
        if len(payload) < 2:
            return
        port = self._ports.get(payload[0])
        if port is not None:
            port._feed(payload[1:])

    def init(self, *, port: int = 1, tx: int | None = None, rx: int | None = None,
             baud: int = 115_200) -> UartPort:
        """Open/configure a secondary UART and return its UartPort. Pins default
        to the board's (``esp.pins.tx`` / ``.rx``)."""
        pins = self._b.pins
        tx = pins.tx if tx is None else tx
        rx = pins.rx if rx is None else rx
        self._b.request(C.UART_INIT, struct.pack(">BbbI", port, tx, rx, baud))
        p = self._ports.get(port)
        if p is None:
            p = self._ports[port] = UartPort(self._b, port, baud)
        p.baudrate, p.is_open = baud, True
        return p

    def port(self, port: int) -> UartPort | None:
        """The open port with this number, or None — for code that didn't keep
        what :meth:`init` returned."""
        return self._ports.get(port)

