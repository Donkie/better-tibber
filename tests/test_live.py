"""Tests for LiveMeterManager (live.py).

Tests that:
- start() spawns one task per device
- async_stop() cancels all tasks
- _run() delivers subscription frames to the coordinator callback
- _run() reconnects after a dropped connection
- _run() stops cleanly when the stop event is set
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tibber_app.live import LiveMeterManager

_SLEEP = "custom_components.tibber_app.live.asyncio.sleep"
_QUERY = "subscription { liveMeasurement { power } }"
_FIELD = "liveMeasurement"


def _manager(hass) -> tuple[LiveMeterManager, MagicMock]:
    """Return (manager, coordinator mock) backed by the real test hass."""
    coordinator = MagicMock()
    coordinator.hass = hass
    return LiveMeterManager(coordinator), coordinator


class TestStartStop:
    async def test_start_creates_one_task_per_device(self, hass):
        manager, coordinator = _manager(hass)

        async def blocking(*args, stop=None, **kwargs):
            await asyncio.sleep(100)
            return
            yield  # async generator

        coordinator.client.subscribe = blocking
        manager.start(["p1", "p2"], ["b1"])
        assert len(manager._tasks) == 3
        await manager.async_stop()

    async def test_start_creates_tasks_for_pulse_only(self, hass):
        manager, coordinator = _manager(hass)

        async def blocking(*args, stop=None, **kwargs):
            await asyncio.sleep(100)
            return
            yield

        coordinator.client.subscribe = blocking
        manager.start(["pulse-1"], [])
        assert len(manager._tasks) == 1
        await manager.async_stop()

    async def test_async_stop_cancels_all_tasks(self, hass):
        manager, coordinator = _manager(hass)

        async def blocking(*args, stop=None, **kwargs):
            await asyncio.sleep(100)
            return
            yield

        coordinator.client.subscribe = blocking
        manager.start(["p1", "p2"], [])
        await hass.async_block_till_done()

        await manager.async_stop()

        assert all(t.done() for t in manager._tasks)

    async def test_start_empty_does_not_create_tasks(self, hass):
        manager, _ = _manager(hass)
        manager.start([], [])
        assert manager._tasks == []


class TestRun:
    async def test_delivers_frames_to_callback(self, hass):
        manager, coordinator = _manager(hass)
        received: list = []

        async def fake_subscribe(query, variables=None, stop=None):
            yield {_FIELD: {"power": 100}}
            yield {_FIELD: {"power": 200}}
            stop.set()

        coordinator.client.subscribe = fake_subscribe

        with patch(_SLEEP, new=AsyncMock()):
            await manager._run(
                "p1",
                _QUERY,
                _FIELD,
                lambda did, data: received.append((did, data)),
            )

        assert received == [
            ("p1", {"power": 100}),
            ("p1", {"power": 200}),
        ]

    async def test_skips_frames_with_no_field(self, hass):
        """Frames where data.get(field) is None/empty are silently dropped."""
        manager, coordinator = _manager(hass)
        received: list = []

        async def fake_subscribe(query, variables=None, stop=None):
            yield {"otherField": {"x": 1}}  # wrong field
            yield {_FIELD: {"power": 42}}
            stop.set()

        coordinator.client.subscribe = fake_subscribe

        with patch(_SLEEP, new=AsyncMock()):
            await manager._run(
                "p1",
                _QUERY,
                _FIELD,
                lambda did, data: received.append(data),
            )

        assert received == [{"power": 42}]

    async def test_reconnects_after_exception(self, hass):
        """An exception from subscribe is logged and the loop retries."""
        manager, coordinator = _manager(hass)
        call_count = 0
        received: list = []

        async def flaky_subscribe(query, variables=None, stop=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("socket dropped")
            yield {_FIELD: {"power": 99}}
            stop.set()

        coordinator.client.subscribe = flaky_subscribe

        with patch(_SLEEP, new=AsyncMock()):
            await manager._run(
                "p1",
                _QUERY,
                _FIELD,
                lambda did, data: received.append(data),
            )

        assert call_count == 2
        assert received == [{"power": 99}]

    async def test_reconnect_sleep_duration(self, hass):
        """A 30-second sleep is observed between reconnect attempts."""
        manager, coordinator = _manager(hass)
        sleep_calls: list[float] = []

        async def fail_then_stop(query, variables=None, stop=None):
            if not sleep_calls:
                raise ConnectionError("first drop")
            stop.set()
            return
            yield

        coordinator.client.subscribe = fail_then_stop

        async def record_sleep(n):
            sleep_calls.append(n)

        with patch(_SLEEP, new=AsyncMock(side_effect=record_sleep)):
            await manager._run("p1", _QUERY, _FIELD, lambda *_: None)

        assert sleep_calls == [30]

    async def test_cancelled_error_propagates(self, hass):
        """CancelledError from subscribe is re-raised, not swallowed."""
        manager, coordinator = _manager(hass)

        async def cancel_sub(query, variables=None, stop=None):
            raise asyncio.CancelledError
            yield  # async generator

        coordinator.client.subscribe = cancel_sub

        with pytest.raises(asyncio.CancelledError):
            await manager._run("p1", _QUERY, _FIELD, lambda *_: None)

    async def test_stop_event_prevents_reconnect(self, hass):
        """If stop is set after a connection drop, there is no retry sleep."""
        manager, coordinator = _manager(hass)

        async def fail_sub(query, variables=None, stop=None):
            stop.set()
            raise ConnectionError("dropped")
            yield

        coordinator.client.subscribe = fail_sub
        sleep_mock = AsyncMock()

        with patch(_SLEEP, new=sleep_mock):
            await manager._run("p1", _QUERY, _FIELD, lambda *_: None)

        sleep_mock.assert_not_called()
