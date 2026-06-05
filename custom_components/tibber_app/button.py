"""Button platform for the Tibber app integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TibberConfigEntry
from .coordinator import TibberDataUpdateCoordinator
from .entity import TibberHomeEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the refresh button (one per home device)."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TibberRefreshButton(coordinator, home_id) for home_id in coordinator.home_titles
    )


class TibberRefreshButton(TibberHomeEntity, ButtonEntity):
    """Force an immediate data refresh."""

    _attr_translation_key = "refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: TibberDataUpdateCoordinator, home_id: str) -> None:
        super().__init__(coordinator, home_id, "refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
