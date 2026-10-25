"""AsyncBridge: await any call, overlap them with gather, stream events."""
import asyncio
import struct

import pytest

from esplink import AsyncBridge
from esplink import constants as C
from esplink.gpio import EdgeEvent


def _async(fw, scenario):
    """Run an async scenario(esp) against the fake firmware."""
    async def runner():
        async with AsyncBridge(transport=fw.transport, upgrade_baud=False,
                               reset_on_open=False) as esp:
            await scenario(esp)
    asyncio.run(runner())


def test_await_methods_and_values(fw):
    async def scenario(esp):
        await esp.gpio.mode(2, "output")
        assert await esp.gpio.write(2, 1) == 1      # sub-API method
        assert isinstance(await esp.ping(), float)   # Bridge method
        assert C.Cap.WIFI in esp.info.caps           # plain value, no await
    _async(fw, scenario)


def test_gather_overlaps_calls(fw):
    async def scenario(esp):
        await esp.gpio.mode(2, "output")
        await esp.gpio.write(2, 1)
        assert await asyncio.gather(*(esp.gpio.read(2) for _ in range(8))) == [1] * 8
    _async(fw, scenario)


def test_event_stream_subscribes_before_first_await(fw):
    async def scenario(esp):
        stream = esp.events(C.GPIO_EDGE_EVT, EdgeEvent.parse)
        fw.emit(C.GPIO_EDGE_EVT, bytes([4, 0]) + struct.pack(">I", 12345))  # before iterating
        ev = await asyncio.wait_for(anext(stream), timeout=2.0)
        assert (ev.pin, ev.level, ev.millis) == (4, 0, 12345)
        await stream.aclose()                        # unsubscribes
    _async(fw, scenario)


def test_wrap_shares_and_does_not_close(bridge):
    async def scenario():
        async with AsyncBridge.wrap(bridge) as esp:
            assert await esp.free_heap()
    asyncio.run(scenario())
    assert bridge.ping() > 0                         # still open for its owner


def test_not_connected_explains_itself():
    with pytest.raises(RuntimeError, match="not connected"):
        AsyncBridge(ble=False).gpio  # noqa: B018


def test_subapi_method_named_like_a_subapi_is_callable(fw):
    # Gpio.watch shares its name with the esp.watch sub-API; it must still be a method.
    async def scenario(esp):
        await esp.gpio.mode(4, "input_pullup")
        await esp.gpio.watch(4, edge="falling")
    _async(fw, scenario)


def test_unstarted_stream_unsubscribes_on_close(fw):
    async def scenario(esp):
        stream = esp.events(C.GPIO_EDGE_EVT)
        await stream.aclose()
        assert not esp.bridge._handlers.get(C.GPIO_EDGE_EVT)
    _async(fw, scenario)


def test_timed_out_wait_keeps_the_stream(fw):
    async def scenario(esp):
        stream = esp.events(C.GPIO_EDGE_EVT, EdgeEvent.parse)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(anext(stream), timeout=0.05)
        fw.emit(C.GPIO_EDGE_EVT, bytes([4, 1]) + struct.pack(">I", 7))
        assert (await asyncio.wait_for(anext(stream), timeout=2.0)).millis == 7
        await stream.aclose()
    _async(fw, scenario)
