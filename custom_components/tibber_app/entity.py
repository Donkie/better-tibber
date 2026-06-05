"""Base entity + device-registry helpers for the Tibber app integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import TibberDataUpdateCoordinator, TibberDevice


class TibberEntity(CoordinatorEntity[TibberDataUpdateCoordinator]):
    """Base class wiring an entity to a discovered device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        device: TibberDevice,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._device = device
        self._key = key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{device.id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.type.replace("_", " ").title(),
            via_device=(DOMAIN, device.home_id),
        )


class TibberHomeEntity(CoordinatorEntity[TibberDataUpdateCoordinator]):
    """Base class for entities attached to a home (price, peak control, away mode)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TibberDataUpdateCoordinator,
        home_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._home_id = home_id
        self._key = key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{home_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, home_id)},
            name=coordinator.home_titles.get(home_id, "Tibber home"),
            manufacturer=MANUFACTURER,
            model="Home",
            entry_type=None,
        )

    @property
    def _home(self) -> dict:
        return self.coordinator.data.homes.get(self._home_id, {})
