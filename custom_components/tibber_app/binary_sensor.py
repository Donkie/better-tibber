"""Binary sensor platform for the Tibber app integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TibberConfigEntry
from .const import (
    GIZMO_BATTERY,
    GIZMO_ELECTRIC_VEHICLE,
    GIZMO_EV_CHARGER,
    GIZMO_REAL_TIME_METER,
)
from .coordinator import TibberDataUpdateCoordinator, TibberDevice
from .entity import TibberEntity


@dataclass(frozen=True, kw_only=True)
class TibberBinaryDescription(BinarySensorEntityDescription):
    """Binary sensor description with a value extractor."""

    value_fn: Callable[[dict[str, Any]], bool | None]


VEHICLE_BINARY: tuple[TibberBinaryDescription, ...] = (
    TibberBinaryDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: v.get("isAlive"),
    ),
    TibberBinaryDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda v: v.get("chargingStatus") == "CHARGING",
    ),
)

CHARGER_BINARY: tuple[TibberBinaryDescription, ...] = (
    TibberBinaryDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: v.get("isAlive"),
    ),
)

BATTERY_BINARY: tuple[TibberBinaryDescription, ...] = (
    TibberBinaryDescription(
        key="grid_rewards_enabled",
        translation_key="grid_rewards_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda v: v.get("isGridRewardsEnabled"),
    ),
)

# Live Pulse binary sensors read from coordinator.data.live[pulse_id].
PULSE_BINARY: tuple[TibberBinaryDescription, ...] = (
    TibberBinaryDescription(
        key="peak_exceeded",
        translation_key="peak_exceeded",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda v: (
            (v.get("peakControlConsumptionState") or "NORMAL") != "NORMAL"
        ),
    ),
)


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber app binary sensors."""
    coordinator = entry.runtime_data.coordinator
    entities: list[BinarySensorEntity] = []

    for dev in coordinator.devices_of_type(GIZMO_ELECTRIC_VEHICLE):
        entities += [
            TibberDeviceBinary(coordinator, dev, desc, "vehicles")
            for desc in VEHICLE_BINARY
        ]
    for dev in coordinator.devices_of_type(GIZMO_EV_CHARGER):
        entities += [
            TibberDeviceBinary(coordinator, dev, desc, "chargers")
            for desc in CHARGER_BINARY
        ]
    for dev in coordinator.devices_of_type(GIZMO_BATTERY):
        entities += [
            TibberDeviceBinary(coordinator, dev, desc, "batteries")
            for desc in BATTERY_BINARY
        ]
    for dev in coordinator.devices_of_type(GIZMO_REAL_TIME_METER):
        entities += [TibberPulseBinary(coordinator, dev, desc) for desc in PULSE_BINARY]

    async_add_entities(entities)


class TibberDeviceBinary(TibberEntity, BinarySensorEntity):
    """Binary sensor backed by a device node in a coordinator collection."""

    entity_description: TibberBinaryDescription

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        device: TibberDevice,
        description: TibberBinaryDescription,
        collection: str,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description
        self._collection = collection

    @property
    def is_on(self) -> bool | None:
        node = getattr(self.coordinator.data, self._collection).get(self._device.id)
        if node is None:
            return None
        return self.entity_description.value_fn(node)


class TibberPulseBinary(TibberEntity, BinarySensorEntity):
    """Live Pulse binary sensor reading from coordinator.data.live."""

    entity_description: TibberBinaryDescription

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        device: TibberDevice,
        description: TibberBinaryDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        node = self.coordinator.data.live.get(self._device.id)
        if node is None:
            return None
        return self.entity_description.value_fn(node)
