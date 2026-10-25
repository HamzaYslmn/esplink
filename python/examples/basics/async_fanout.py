"""asyncio: AsyncBridge is Bridge with `await`; gather() overlaps calls on the wire.

    uv run basics/async_fanout.py
"""
import asyncio

from esplink import AsyncBridge


async def main():
    async with AsyncBridge() as esp:
        readings = await asyncio.gather(*(esp.adc.read(pin) for pin in (34, 35, 36, 39)))
        print("ADC 34/35/36/39:", readings)


asyncio.run(main())
