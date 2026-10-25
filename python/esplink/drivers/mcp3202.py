"""MCP3202 — 12-bit, 2-channel SPI ADC: the MCP3208 driver with ``channels=2``
(see mcp3208.py for usage, wiring and the command frame)."""
from __future__ import annotations

from .mcp3208 import MCP3208


class MCP3202(MCP3208):
    def __init__(self, bridge, **kw):
        super().__init__(bridge, channels=2, **kw)
