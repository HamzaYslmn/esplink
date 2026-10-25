"""Run the board as an MCP server so an AI agent can drive it, plus one custom tool.

Without a custom tool you don't need this file: the `esplink-mcp` command is
the same server. For Claude Code:  claude mcp add esplink -- esplink-mcp
Reference: docs/MCP.md.

    uv run system/mcp_server.py
"""
import time

from esplink.mcp import BridgeManager, build_server

mgr = BridgeManager()
server = build_server(mgr)


@server.tool
def blink(pin: int, times: int = 3) -> str:
    """Blink an LED on `pin` a few times."""
    esp = mgr.bridge()
    esp.gpio.mode(pin, "output")
    for _ in range(times):
        esp.gpio.write(pin, 1)
        time.sleep(0.2)
        esp.gpio.write(pin, 0)
        time.sleep(0.2)
    return f"blinked GPIO{pin} {times} times"


server.run()
