"""Button platform for the Tibber app integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TibberConfigEntry
from .const import GIZMO_ELECTRIC_VEHICLE, VEHICLE_DEPARTURE_SUFFIX, WEEKDAYS
from .coordinator import TibberDataUpdateCoordinator, TibberDevice
from .entity import TibberEntity, TibberHomeEntity
from .vehicle_settings import parse_departure_time

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up refresh and vehicle schedule buttons."""
    coordinator = entry.runtime_data.coordinator
    entities: list[ButtonEntity] = [
        TibberRefreshButton(coordinator, home_id)
        for home_id in coordinator.home_titles
    ]
    for dev in coordinator.devices_of_type(GIZMO_ELECTRIC_VEHICLE):
        entities += [
            TibberVehicleActionButton(coordinator, dev, key, prefix)
            for key, prefix in VEHICLE_ACTIONS
        ]
        monday_key = coordinator.vehicle_setting_key(
            dev.id, VEHICLE_DEPARTURE_SUFFIX.format(day="monday")
        )
        if monday_key is not None:
            entities.append(TibberClearAllDepartureTimesButton(coordinator, dev))
    async_add_entities(entities)


class TibberRefreshButton(TibberHomeEntity, ButtonEntity):
    """Force an immediate data refresh."""

    _attr_translation_key = "refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: TibberDataUpdateCoordinator, home_id: str) -> None:
        super().__init__(coordinator, home_id, "refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()


class TibberClearAllDepartureTimesButton(TibberEntity, ButtonEntity):
    """Clear every weekday that currently has a departure time."""

    _attr_translation_key = "clear_all_departure_times"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: TibberDataUpdateCoordinator, device: TibberDevice
    ) -> None:
        super().__init__(coordinator, device, "clear_all_departure_times")

    async def async_press(self) -> None:
        node = self.coordinator.data.vehicles.get(self._device.id) or {}
        current_settings = {
            setting.get("key"): setting.get("value")
            for setting in node.get("userSettings") or []
        }
        setting_keys = []
        for day in WEEKDAYS:
            suffix = VEHICLE_DEPARTURE_SUFFIX.format(day=day)
            key = self.coordinator.vehicle_setting_key(self._device.id, suffix)
            if (
                key is not None
                and parse_departure_time(current_settings.get(key)) is not None
            ):
                setting_keys.append(key)

        await self.coordinator.async_clear_vehicle_departure_times(
            self._device.id, self._device.home_id, setting_keys
        )


# The app's vehicle screen renders server-sent actionButtons; pressing one writes
# its opaque action string back as the "action" vehicle setting (the app's
# SmartChargingAction.RemoteAction). The trailing id changes with each state, so
# the action must always come from the latest poll. Verified on a real vehicle:
# - "Charge right away" (grpc.vehicle.startCharging:…) is offered while plugged
#   in and waiting on the plan. Pressing it starts charging within seconds,
#   smartChargingStatus goes "on" -> "suspended", the plan empties, and
#   smartCharging.isEnabled stays true.
# - While suspended, "Turn on Smart Charging" (grpc.vehicle.enableSmartCharging:…)
#   is offered; pressing it stops charging and restores the plan.
VEHICLE_ACTIONS = (
    ("charge_now", "grpc.vehicle.startCharging"),
    ("resume_smart_charging", "grpc.vehicle.enableSmartCharging"),
)


class TibberVehicleActionButton(TibberEntity, ButtonEntity):
    """Send a vehicle action, available only while Tibber offers it."""

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        device: TibberDevice,
        key: str,
        prefix: str,
    ) -> None:
        super().__init__(coordinator, device, key)
        self._attr_translation_key = key
        self._prefix = prefix

    def _action(self) -> str | None:
        node = self.coordinator.data.vehicles.get(self._device.id) or {}
        return next(
            (
                b["action"]
                for b in node.get("actionButtons") or []
                if b.get("enabled") and (b.get("action") or "").startswith(self._prefix)
            ),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self._action() is not None

    async def async_press(self) -> None:
        if (action := self._action()) is None:
            raise HomeAssistantError("Tibber is not offering this action right now")
        await self.coordinator.async_set_vehicle_setting(
            self._device.id, self._device.home_id, "action", action
        )
