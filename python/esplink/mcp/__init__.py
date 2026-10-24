"""MCP (Model Context Protocol) server for esplink.

Exposes every Bridge peripheral (GPIO, ADC/DAC, PWM, I2C, SPI, UART, Wi-Fi,
NVS, filesystem, 1-Wire, ESP-NOW, CAN, MCPWM, Ethernet, camera, OTA, ...) as
MCP tools so an LLM agent can drive an ESP32 over USB or Bluetooth.

    esplink-mcp                 # run as a stdio MCP server (auto-detect port)
    python -m esplink.mcp -p COM7

Or embed it:

    from esplink.mcp import build_server
    build_server(port="COM7").run()

Needs the optional dependency:  pip install "esplink[mcp]"
"""
from .server import BridgeManager, build_server, main

__all__ = ["BridgeManager", "build_server", "main"]
