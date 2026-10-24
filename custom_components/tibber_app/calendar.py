"""Calendar platform: a vehicle's smart-charging plan as events."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TibberConfigEntry
from .const import GIZMO_ELECTRIC_VEHICLE
from .coordinator import TibberDataUpdateCoordinator, TibberDevice, charging_windows
from .entity import TibberEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a charging-plan calendar per vehicle."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TibberChargingPlanCalendar(coordinator, dev)
        for dev in coordinator.devices_of_type(GIZMO_ELECTRIC_VEHICLE)
    )


class TibberChargingPlanCalendar(TibberEntity, CalendarEntity):
    """One event per planned charge window (only the plan ahead is known)."""

    _attr_translation_key = "charging_plan"

    def __init__(
        self, coordinator: TibberDataUpdateCoordinator, device: TibberDevice
    ) -> None:
        super().__init__(coordinator, device, "charging_plan")

    def _events(self) -> list[CalendarEvent]:
        node = self.coordinator.data.vehicles.get(self._device.id) or {}
        currency = (node.get("charging") or {}).get("currency") or ""
        events = []
        for w in charging_windows(node, dt_util.utcnow()):
            summary = "Charging"
            if w["from_soc"] is not None and w["to_soc"] is not None:
                summary += f" {w['from_soc']}% → {w['to_soc']}%"
            events.append(
                CalendarEvent(
                    start=w["start"],
                    end=w["end"],
                    summary=summary,
                    description=f"{w['energy']:.2f} kWh, {w['cost']:.2f} {currency}",
                )
            )
        return events

    @property
    def event(self) -> CalendarEvent | None:
        # Windows that already ended are dropped, so the first is current or next.
        events = self._events()
        return events[0] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [e for e in self._events() if e.start < end_date and e.end > start_date]
