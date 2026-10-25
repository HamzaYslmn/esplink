"""Frame codec: COBS framing + CRC-16/CCITT-FALSE.

Wire format (see docs/PROTOCOL.md):
    logical frame = flags u8 | seq u8 | cmd u16 BE | payload | crc16 BE
    on the wire   = COBS(logical) + b"\\x00"
"""
from __future__ import annotations

import binascii
import re
import struct
from dataclasses import dataclass

from .constants import FLAG_ERROR, FLAG_EVENT, MAX_PAYLOAD
from .errors import ProtocolError

_HDR = struct.Struct(">BBH")

# ---- CRC-16/CCITT-FALSE ------------------------------------------------------
# binascii.crc_hqx implements the CCITT algorithm (poly 0x1021, no reflection)
# in C. Seeded with 0xFFFF it is bit-identical to CRC-16/CCITT-FALSE — verified
# against the old pure-Python table loop and the firmware's crc16_ccitt.
# About 15x faster than a pure-Python per-byte loop on the hot path.
# Accepts any buffer-protocol object (bytes, bytearray, memoryview).


def crc16_ccitt(data) -> int:
    return binascii.crc_hqx(data, 0xFFFF)


# ---- COBS ----------------------------------------------------------------------


_RUN = re.compile(rb"[^\x00]+")


def cobs_encode(data) -> bytes:
    # Two forms, both Python work per zero or per run instead of per byte
    # (1 KB frames: ~9x faster for binary data, 2-4x for zero-heavy). Zero-heavy
    # data (a mostly-dark OLED framebuffer) goes per run; everything else —
    # every small request — per zero, which measured faster than the regex's
    # fixed cost on short frames.
    if data.count(0) > 64:
        out = bytearray(b"\x01") + data.replace(b"\x00", b"\x01")
        # Each zero became 0x01, the code of an empty block; now patch the code
        # byte (the zero before it) of each non-zero run.
        for m in _RUN.finditer(data):
            start, end = m.span()
            if end - start >= 254:  # needs mid-run code bytes, which shift the layout
                break
            out[start] = end - start + 1
        else:
            return bytes(out)
    out = bytearray()
    for seg in data.split(b"\x00"):
        while len(seg) >= 254:
            out.append(0xFF)
            out += seg[:254]
            seg = seg[254:]
        out.append(len(seg) + 1)
        out += seg
    return bytes(out)


def cobs_decode(data) -> bytes:
    # The inverse trick: decoded = the wire bytes with every code byte turned
    # back into the zero it stands for, minus the leading code and the code
    # after each 0xFF block (those carry no zero). Walking the code chain is
    # the only per-block Python work: 1.3-3.5x faster than copying blocks.
    if 0 in data:
        raise ProtocolError("zero byte inside COBS frame")
    out = bytearray(data)
    n = len(data)
    i = 0
    drop = [0]
    while i < n:
        code = data[i]
        out[i] = 0
        i += code
        if code == 0xFF and i < n:
            drop.append(i)
    if i > n:
        raise ProtocolError("truncated COBS block")
    for j in reversed(drop):
        del out[j]
    return bytes(out)


# ---- frames ---------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    """A decoded logical frame: flags, seq, cmd (u16), and payload bytes."""
    flags: int
    seq: int
    cmd: int
    payload: bytes

    @property
    def is_event(self) -> bool:
        """True if this is an unsolicited event frame (FLAG_EVENT set)."""
        return bool(self.flags & FLAG_EVENT)

    @property
    def is_error(self) -> bool:
        """True if this frame reports a remote error (FLAG_ERROR set)."""
        return bool(self.flags & FLAG_ERROR)


def encode_frame(flags: int, seq: int, cmd: int, payload: bytes = b"") -> bytes:
    """Logical frame -> wire bytes (COBS + 0x00 delimiter)."""
    plen = len(payload)
    if plen > MAX_PAYLOAD:
        raise ProtocolError(f"payload too large: {plen} > {MAX_PAYLOAD}")
    # Assemble header + payload + CRC into a single buffer instead of chaining
    # bytes concatenations — reduces three intermediate copies to zero.
    logical = bytearray(4 + plen + 2)
    _HDR.pack_into(logical, 0, flags, seq, cmd)
    logical[4:4 + plen] = payload
    struct.pack_into(">H", logical, 4 + plen, crc16_ccitt(memoryview(logical)[:4 + plen]))
    return cobs_encode(logical) + b"\x00"


def decode_frame(encoded: bytes) -> Frame:
    """Wire bytes between delimiters -> logical Frame. Raises ProtocolError."""
    logical = cobs_decode(encoded)
    if len(logical) < 6:
        raise ProtocolError(f"frame too short: {len(logical)} bytes")
    (crc,) = struct.unpack_from(">H", logical, len(logical) - 2)
    if crc16_ccitt(memoryview(logical)[:-2]) != crc:
        raise ProtocolError("CRC mismatch")
    flags, seq, cmd = _HDR.unpack_from(logical)
    return Frame(flags, seq, cmd, logical[4:-2])


# ---- wire-format helpers shared by the sub-API modules ---------------------------

CHUNK = MAX_PAYLOAD - 8  # max blob bytes per request (leaves room for header + CRC)


def chunks(data, size: int = CHUNK):
    """Yield ``data`` in ``size``-byte slices — the splitting loop the blob write
    paths (fs/i2s/ota) share."""
    for i in range(0, len(data), size):
        yield data[i:i + size]


def lp(s: str | bytes) -> bytes:
    """Length-prefixed string (len u8 | bytes) — the protocol's string format."""
    b = s.encode() if isinstance(s, str) else bytes(s)
    if len(b) > 255:
        raise ProtocolError(f"string too long for length prefix: {len(b)} bytes")
    return bytes([len(b)]) + b


def ip_str(b: bytes) -> str:
    """4 raw bytes -> dotted-quad string."""
    return ".".join(str(x) for x in b)


def mac_to_str(mac: bytes) -> str:
    """6 raw bytes -> 'aa:bb:cc:dd:ee:ff'."""
    return ":".join(f"{x:02x}" for x in mac)


def mac_to_bytes(mac: str | bytes) -> bytes:
    """'aa:bb:cc:dd:ee:ff' / 'aa-bb-...' / 'aabbccddeeff' -> 6 raw bytes."""
    if isinstance(mac, (bytes, bytearray)):
        if len(mac) != 6:
            raise ValueError(f"MAC must be 6 bytes, got {len(mac)}")
        return bytes(mac)
    digits = mac.replace(":", "").replace("-", "")
    if len(digits) != 12:
        raise ValueError(f"invalid MAC address {mac!r}")
    return bytes.fromhex(digits)


class FrameSplitter:
    """Accumulates raw serial bytes and yields COBS chunks between 0x00 delimiters."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._pos = 0  # index of the first unconsumed byte — avoids an O(n) left-shift after every frame

    def feed(self, data: bytes) -> list[bytes]:
        """Add raw bytes; return the list of complete COBS chunks now available
        (the data between 0x00 delimiters), buffering any partial tail."""
        chunks: list[bytes] = []
        buf = self._buf
        buf += data
        while True:
            i = buf.find(0, self._pos)  # only search from the unconsumed tail
            if i < 0:
                break
            if i > self._pos:
                chunks.append(bytes(buf[self._pos:i]))
            self._pos = i + 1
        # Reclaim consumed bytes in amortized batches rather than after every frame,
        # so the left-shift cost is O(1) amortized instead of O(n) per frame.
        if self._pos > 4096:
            del buf[: self._pos]
            self._pos = 0
        return chunks

    def reset(self) -> None:
        """Discard any buffered partial frame (e.g. after a reconnect)."""
        self._buf.clear()
        self._pos = 0
