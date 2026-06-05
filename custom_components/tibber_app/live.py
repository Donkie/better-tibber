"""Background WebSocket listeners for live device state.

One task per device subscribes to its live feed and pushes each frame into the
coordinator: Pulse meters via ``liveMeasurement`` and home batteries via
``batteryState``. Sockets are best-effort; on any drop we back off and reconnect,
while the polling coordinator keeps values fresh in the meantime.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from . import queries
from .coordinator import TibberDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

_RECONNECT_DELAY = 30  # seconds between reconnect attempts


class LiveMeterManager:
    """Owns the per-device live subscription tasks for one config entry."""

    def __init__(self, coordinator: TibberDataUpdateCoordinator) -> None:
        self._coordinator = coordinator
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    def start(self, pulse_ids: list[str], battery_ids: list[str]) -> None:
        """Spawn a reconnecting listener task for each live device."""
        for pulse_id in pulse_ids:
            self._spawn(
                pulse_id,
                queries.SUB_LIVE_MEASUREMENT,
                "liveMeasurement",
                self._coordinator.update_live,
            )
        for battery_id in battery_ids:
            self._spawn(
                battery_id,
                queries.SUB_BATTERY_STATE,
                "batteryState",
                self._coordinator.update_battery_live,
            )

    def _spawn(
        self,
        device_id: str,
        query: str,
        field: str,
        callback: Callable[[str, dict], None],
    ) -> None:
        self._tasks.append(
            self._coordinator.hass.async_create_background_task(
                self._run(device_id, query, field, callback),
                name=f"tibber_app_live_{field}_{device_id}",
            )
        )

    async def async_stop(self) -> None:
        """Stop all listener tasks."""
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    async def _run(
        self,
        device_id: str,
        query: str,
        field: str,
        callback: Callable[[str, dict], None],
    ) -> None:
        while not self._stop.is_set():
            try:
                async for data in self._coordinator.client.subscribe(
                    query, {"deviceId": device_id}, stop=self._stop
                ):
                    payload = data.get(field)
                    if payload:
                        callback(device_id, payload)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the loop alive
                _LOGGER.debug("Live %s %s dropped: %s", field, device_id, err)
            if not self._stop.is_set():
                await asyncio.sleep(_RECONNECT_DELAY)
