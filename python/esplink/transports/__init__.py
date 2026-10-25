"""Transports: byte links the Bridge protocol runs over (serial, BLE, mock).

A transport provides:
    read() -> bytes        # whatever is available (may block briefly, b"" ok)
    write(data: bytes)     # send raw bytes
    close()
    usb_chip: str | None   # adapter hint for baud upgrade ("cp210x", ...)
    needs_auth: bool       # True = Bridge sends SYS_AUTH before the handshake
    has_baud: bool         # False skips baud negotiation; when True, also:
    set_baudrate(baud)
    pulse_reset()          # (only called when needs_auth is False)

Optional flow-control attributes (a transport sets them to opt in; absent ==
unbounded, the serial default):
    max_inflight: int      # cap on request bytes written but not yet replied —
                           # Bridge blocks writers past it so pipelined traffic
                           # can't overflow the firmware's link RX buffer (BLE)
    burst_window: int      # same cap for fire-and-forget send(); past it send()
                           # inserts a ping fence to drain the in-flight window
"""
from .serial import PortInfo, SerialTransport, find_ports
from .mock import MockTransport
from .tcp import TcpTransport, WifiDeviceInfo, find_wifi_devices

__all__ = [
    "MockTransport",
    "PortInfo",
    "SerialTransport",
    "TcpTransport",
    "WifiDeviceInfo",
    "find_ports",
    "find_wifi_devices",
]
