"""Number platform for the Tibber app integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TibberConfigEntry
from .const import GIZMO_ELECTRIC_VEHICLE, GIZMO_EV_CHARGER, VEHICLE_SOC_KEY
from .coordinator import TibberDataUpdateCoordinator, TibberDevice
from .entity import TibberEntity, TibberHomeEntity

# Charger numeric settings: (setting key, translation key, min, max, step).
CHARGER_NUMBERS: tuple[tuple[str, str, float, float, float], ...] = (
    ("maxCurrentCharger", "max_current", 6, 32, 1),
    ("mainFuseSize", "main_fuse", 10, 63, 1),
    ("offlineFallbackCurrent", "offline_fallback_current", 0, 32, 1),
)


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber app number entities."""
    coordinator = entry.runtime_data.coordinator
    entities: list[NumberEntity] = []

    for dev in coordinator.devices_of_type(GIZMO_ELECTRIC_VEHICLE):
        entities.append(TibberVehicleSocNumber(coordinator, dev))
    for dev in coordinator.devices_of_type(GIZMO_EV_CHARGER):
        entities += [
            TibberChargerNumber(coordinator, dev, key, tkey, lo, hi, step)
            for key, tkey, lo, hi, step in CHARGER_NUMBERS
        ]
    for home_id in coordinator.home_titles:
        entities.append(TibberPeakLimitNumber(coordinator, home_id))

    async_add_entities(entities)


class TibberVehicleSocNumber(TibberEntity, NumberEntity):
    """Manual state-of-charge override (the repo's original use case)."""

    _attr_translation_key = "manual_soc"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = NumberDeviceClass.BATTERY
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self, coordinator: TibberDataUpdateCoordinator, device: TibberDevice
    ) -> None:
        super().__init__(coordinator, device, "manual_soc")

    @property
    def native_value(self) -> float | None:
        node = self.coordinator.data.vehicles.get(self._device.id) or {}
        return (node.get("battery") or {}).get("level")

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_vehicle_setting(
            self._device.id, self._device.home_id, VEHICLE_SOC_KEY, int(value)
        )


class TibberChargerNumber(TibberEntity, NumberEntity):
    """A numeric charger setting written via setVehicleChargerSettings."""

    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        device: TibberDevice,
        setting_key: str,
        translation_key: str,
        min_value: float,
        max_value: float,
        step: float,
    ) -> None:
        super().__init__(coordinator, device, translation_key)
        self._setting_key = setting_key
        self._attr_translation_key = translation_key
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step

    @property
    def native_value(self) -> float | None:
        node = self.coordinator.data.chargers.get(self._device.id) or {}
        for setting in node.get("userSettings") or []:
            if setting.get("key") == self._setting_key:
                try:
                    return float(setting.get("value"))
                except (TypeError, ValueError):
                    return None
        return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_charger_setting(
            self._device.id, self._device.home_id, self._setting_key, int(value)
        )


class TibberPeakLimitNumber(TibberHomeEntity, NumberEntity):
    """Peak-control hourly consumption limit (kWh/h)."""

    _attr_translation_key = "peak_limit"
    _attr_native_unit_of_measurement = "kWh"
    _attr_native_step = 0.1
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: TibberDataUpdateCoordinator, home_id: str) -> None:
        super().__init__(coordinator, home_id, "peak_limit")

    @property
    def _peak(self) -> dict[str, Any]:
        return self._home.get("peakControl") or {}

    @property
    def available(self) -> bool:
        return super().available and self._peak.get("hasRealTimeDevice") is not False

    @property
    def native_min_value(self) -> float:
        return self._peak.get("lowerBound") or 0

    @property
    def native_max_value(self) -> float:
        return self._peak.get("upperBound") or 100

    @property
    def native_value(self) -> float | None:
        return self._peak.get("consumptionLimit")

    async def async_set_native_value(self, value: float) -> None:
        is_active = bool(self._peak.get("isActive"))
        await self.coordinator.async_set_peak_control(self._home_id, is_active, value)
