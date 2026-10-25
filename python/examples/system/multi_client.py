"""Many programs, one board: one MCP server owns the link, any number of
clients (other processes or machines) share it over HTTP.

A board's link can only be opened once (and most OSes allow a single BLE
connection per device), so start the owner first, in another terminal:

    uv run esplink-mcp --transport http --port-num 8191
    uv run system/multi_client.py
"""
import asyncio

from fastmcp import Client


async def client(n):
    async with Client("http://127.0.0.1:8191/mcp") as c:
        info = (await c.call_tool("system_info", {})).data
        await c.call_tool("system_ping", {})
        print(f"client {n}: {info['chip']} {info['mac']}")


async def main():
    await asyncio.gather(*(client(i) for i in range(3)))


asyncio.run(main())
