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
        if name in Bridge._SUBAPIS:
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

    def events(self, cmd: int, parse=None):
        """``async for`` over firmware event ``cmd`` — payload bytes, or
        ``parse(payload)`` (e.g. ``EdgeEvent.parse``, ``WatchEvent.parse``).
        Subscribed from this call on; leaving the loop unsubscribes."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(payload: bytes) -> None:  # reader thread -> event loop
            item = parse(payload) if parse else payload
            if item is not None:
                loop.call_soon_threadsafe(queue.put_nowait, item)

        self._target.on_event(cmd, on_event)

        async def stream():
            try:
                while True:
                    yield await queue.get()
            finally:
                self._target.off_event(cmd, on_event)
        return stream()
