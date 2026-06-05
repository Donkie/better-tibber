"""Time platform: the weekly EV smart-charging departure schedule.

Each vehicle exposes one time entity per weekday, backed by the
``offline.vehicle.departureTimes.<day>`` user setting ("HH:MM"). Together they form
the weekly smart-charging schedule shown in the Tibber app.
"""

from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TibberConfigEntry
from .const import GIZMO_ELECTRIC_VEHICLE, VEHICLE_DEPARTURE_KEY, WEEKDAYS
from .coordinator import TibberDataUpdateCoordinator, TibberDevice
from .entity import TibberEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a departure-time entity per weekday for each vehicle."""
    coordinator = entry.runtime_data.coordinator
    entities: list[TimeEntity] = []
    for dev in coordinator.devices_of_type(GIZMO_ELECTRIC_VEHICLE):
        node = coordinator.data.vehicles.get(dev.id) or {}
        keys = {s.get("key") for s in node.get("userSettings") or []}
        # Only expose the schedule for vehicles that actually have it.
        if VEHICLE_DEPARTURE_KEY.format(day="monday") not in keys:
            continue
        entities += [TibberDepartureTime(coordinator, dev, day) for day in WEEKDAYS]
    async_add_entities(entities)


class TibberDepartureTime(TibberEntity, TimeEntity):
    """Smart-charging departure time for one weekday."""

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        device: TibberDevice,
        weekday: str,
    ) -> None:
        super().__init__(coordinator, device, f"departure_{weekday}")
        self._weekday = weekday
        self._setting_key = VEHICLE_DEPARTURE_KEY.format(day=weekday)
        self._attr_translation_key = f"departure_{weekday}"

    @property
    def native_value(self) -> dt_time | None:
        node = self.coordinator.data.vehicles.get(self._device.id) or {}
        for setting in node.get("userSettings") or []:
            if setting.get("key") == self._setting_key:
                raw = str(setting.get("value") or "")
                parts = raw.split(":")
                if len(parts) == 2 and all(p.isdigit() for p in parts):
                    return dt_time(int(parts[0]), int(parts[1]))
        return None

    async def async_set_value(self, value: dt_time) -> None:
        await self.coordinator.async_set_vehicle_setting(
            self._device.id,
            self._device.home_id,
            self._setting_key,
            value.strftime("%H:%M"),
        )
