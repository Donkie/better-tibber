"""Select platform for the Tibber app integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TibberConfigEntry
from .const import (
    BATTERY_MODES,
    GIZMO_BATTERY,
    GIZMO_EV_CHARGER,
    PREFERRED_VEHICLE_AUTO,
)
from .coordinator import TibberDataUpdateCoordinator, TibberDevice
from .entity import TibberEntity

_AUTO_LABEL = "Auto"


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber app select entities."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SelectEntity] = []

    for dev in coordinator.devices_of_type(GIZMO_EV_CHARGER):
        entities.append(TibberPreferredVehicleSelect(coordinator, dev))
    for dev in coordinator.devices_of_type(GIZMO_BATTERY):
        entities.append(TibberBatteryModeSelect(coordinator, dev))

    async_add_entities(entities)


class TibberPreferredVehicleSelect(TibberEntity, SelectEntity):
    """Pick which paired vehicle the charger prefers (or Auto)."""

    _attr_translation_key = "preferred_vehicle"

    def __init__(
        self, coordinator: TibberDataUpdateCoordinator, device: TibberDevice
    ) -> None:
        super().__init__(coordinator, device, "preferred_vehicle")

    @property
    def _charger(self) -> dict[str, Any]:
        return self.coordinator.data.chargers.get(self._device.id) or {}

    @property
    def _name_to_id(self) -> dict[str, str]:
        mapping = {_AUTO_LABEL: PREFERRED_VEHICLE_AUTO}
        for vehicle in self._charger.get("vehicles") or []:
            if vehicle.get("name") and vehicle.get("id"):
                mapping[vehicle["name"]] = vehicle["id"]
        return mapping

    @property
    def options(self) -> list[str]:
        return list(self._name_to_id)

    @property
    def current_option(self) -> str | None:
        for vehicle in self._charger.get("vehicles") or []:
            if vehicle.get("isPreferred"):
                return vehicle.get("name")
        return _AUTO_LABEL

    async def async_select_option(self, option: str) -> None:
        vehicle_id = self._name_to_id.get(option, PREFERRED_VEHICLE_AUTO)
        await self.coordinator.async_set_charger_setting(
            self._device.id, self._device.home_id, "preferredVehicleId", vehicle_id
        )


class TibberBatteryModeSelect(TibberEntity, SelectEntity):
    """Select the home battery operation mode."""

    _attr_translation_key = "battery_mode"
    _attr_options = BATTERY_MODES

    def __init__(
        self, coordinator: TibberDataUpdateCoordinator, device: TibberDevice
    ) -> None:
        super().__init__(coordinator, device, "battery_mode")

    @property
    def options(self) -> list[str]:
        node = self.coordinator.data.batteries.get(self._device.id) or {}
        supported = [
            m.get("value")
            for m in node.get("supportedOperationModes") or []
            if m.get("value")
        ]
        return supported or BATTERY_MODES

    @property
    def current_option(self) -> str | None:
        node = self.coordinator.data.batteries.get(self._device.id) or {}
        return (node.get("currentOperationMode") or {}).get("value")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_battery_mode(
            self._device.home_id, self._device.id, option
        )
