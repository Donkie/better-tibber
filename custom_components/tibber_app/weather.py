"""Weather platform: Tibber's per-home hourly forecast."""

from __future__ import annotations

from typing import Any

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfPrecipitationDepth,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TibberConfigEntry
from .coordinator import TibberDataUpdateCoordinator
from .entity import TibberHomeEntity

# Tibber forecast "type" -> Home Assistant condition. Extend as new types appear.
_CONDITION_MAP = {
    "sun": "sunny",
    "clear": "sunny",
    "clearsky": "sunny",
    "partlycloudy": "partlycloudy",
    "fair": "partlycloudy",
    "cloud": "cloudy",
    "cloudy": "cloudy",
    "fog": "fog",
    "rain": "rainy",
    "drizzle": "rainy",
    "sleet": "snowy-rainy",
    "snow": "snowy",
    "thunder": "lightning",
    "wind": "windy",
}


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a weather entity per home that returns forecast data."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TibberWeather(coordinator, home_id)
        for home_id in coordinator.home_titles
        if (coordinator.data.homes.get(home_id) or {}).get("weather")
    )


class TibberWeather(TibberHomeEntity, WeatherEntity):
    """Hourly forecast for a home's location."""

    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_supported_features = WeatherEntityFeature.FORECAST_HOURLY

    def __init__(self, coordinator: TibberDataUpdateCoordinator, home_id: str) -> None:
        super().__init__(coordinator, home_id, "weather")

    @property
    def _entries(self) -> list[dict[str, Any]]:
        return ((self._home.get("weather") or {}).get("entries")) or []

    def _current_entry(self) -> dict[str, Any] | None:
        now = dt_util.now()
        current = None
        for entry in self._entries:
            ts = dt_util.parse_datetime(entry.get("time", ""))
            if ts and ts <= now:
                current = entry
        return current or (self._entries[0] if self._entries else None)

    @property
    def condition(self) -> str | None:
        entry = self._current_entry()
        return _CONDITION_MAP.get(entry.get("type")) if entry else None

    @property
    def native_temperature(self) -> float | None:
        entry = self._current_entry()
        return entry.get("temperature") if entry else None

    def _forecast(self) -> list[Forecast]:
        forecast: list[Forecast] = []
        for entry in self._entries:
            forecast.append(
                Forecast(
                    datetime=entry.get("time"),
                    native_temperature=entry.get("temperature"),
                    condition=_CONDITION_MAP.get(entry.get("type")),
                    native_precipitation=entry.get("precipitation"),
                )
            )
        return forecast

    async def async_forecast_hourly(self) -> list[Forecast]:
        return self._forecast()
