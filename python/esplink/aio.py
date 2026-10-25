"""asyncio: ``await`` every bridge call, and ``async for`` over firmware events.

    async with AsyncBridge(ble=False) as esp:
        await esp.gpio.mode(2, "output")
        # issued together, overlapped on the wire — the Bridge pipelines and the
        # firmware's RTOS tasks run them side by side
        level, mv = await asyncio.gather(esp.gpio.write(2, 1), esp.adc.read_mv(34))
        async for ev in esp.events(C.GPIO_EDGE_EVT, EdgeEvent.parse):
            ...

Each call runs the matching (thread-safe) Bridge method in a worker thread, so
any method — including ones added later — is awaitable with nothing to declare.
"""
from __future__ import annotations

import asyncio
import functools

from .bridge import Bridge


class _Async:
    """Proxy: methods become coroutines; sub-APIs (esp.gpio, ...) stay proxied;
    plain values (info, max_write, ...) pass through."""

    def __init__(self, target):
        self._target = target

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if self._target is None:
            raise RuntimeError("AsyncBridge is not connected — use `async with AsyncBridge(...)`")
        attr = getattr(self._target, name)
        # Callable first: Gpio.watch is a method that shares its name with the
        # esp.watch sub-API. Only the Bridge itself hands out sub-APIs.
        if not callable(attr) and isinstance(self._target, Bridge) and name in Bridge._SUBAPIS:
            return _Async(attr)
        if callable(attr):
            @functools.wraps(attr)
            async def call(*args, **kwargs):
                return await asyncio.to_thread(attr, *args, **kwargs)
            return call
        return attr


class AsyncBridge(_Async):
    """:class:`Bridge` for asyncio; takes the same arguments. Connects off the
    event loop in ``async with``. ``.bridge`` is the underlying sync Bridge."""

    def __init__(self, *args, **kwargs):
        super().__init__(None)
        self._args, self._kwargs, self._owned = args, kwargs, True

    @classmethod
    def wrap(cls, bridge: Bridge) -> AsyncBridge:
        """Share a Bridge you already hold (e.g. ``esplink.connect()``); closing
        the wrapper leaves it open for its owner."""
        esp = cls()
        esp._target, esp._owned = bridge, False
        return esp

    @property
    def bridge(self) -> Bridge:
        return self._target

    async def __aenter__(self) -> AsyncBridge:
        if self._target is None:
            self._target = await asyncio.to_thread(Bridge, *self._args, **self._kwargs)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._target is not None and self._owned:
            await asyncio.to_thread(self._target.close)

    def events(self, cmd: int, parse=None) -> _Events:
        """``async for`` over firmware event ``cmd`` — payload bytes, or
        ``parse(payload)`` (e.g. ``EdgeEvent.parse``, ``WatchEvent.parse``).
        Subscribed from this call on; ``aclose()`` (or leaving ``async with``)
        unsubscribes, iterated or not."""
        return _Events(self._target, cmd, parse)


class _Events:
    """Event stream. A class, not an async generator: a generator's cleanup never
    runs if it was never started, and a timed-out ``anext`` would end it."""

    def __init__(self, bridge: Bridge, cmd: int, parse):
        self._b, self._cmd, self._parse = bridge, cmd, parse
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue = asyncio.Queue()
        bridge.on_event(cmd, self._on_event)

    def _on_event(self, payload: bytes) -> None:  # Bridge event thread -> event loop
        item = self._parse(payload) if self._parse else payload
        if item is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._queue.get()

    async def aclose(self) -> None:
        self._b.off_event(self._cmd, self._on_event)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()
