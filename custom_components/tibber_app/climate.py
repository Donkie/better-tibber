"""Climate platform for the Tibber app integration (thermostats)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TibberConfigEntry
from .const import GIZMO_THERMOSTAT
from .coordinator import TibberDataUpdateCoordinator, TibberDevice
from .entity import TibberEntity

# Best-effort mapping between Tibber mode strings and HA HVAC modes.
_MODE_TO_HVAC = {
    "HEAT": HVACMode.HEAT,
    "COOL": HVACMode.COOL,
    "AUTO": HVACMode.AUTO,
    "HEAT_COOL": HVACMode.HEAT_COOL,
    "FAN": HVACMode.FAN_ONLY,
    "DRY": HVACMode.DRY,
}
_HVAC_TO_MODE = {v: k for k, v in _MODE_TO_HVAC.items()}


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TibberConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber thermostats as climate entities."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TibberThermostat(coordinator, dev)
        for dev in coordinator.devices_of_type(GIZMO_THERMOSTAT)
    )


class TibberThermostat(TibberEntity, ClimateEntity):
    """A Tibber-connected thermostat."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 0.5

    def __init__(
        self, coordinator: TibberDataUpdateCoordinator, device: TibberDevice
    ) -> None:
        super().__init__(coordinator, device, "thermostat")

    @property
    def _node(self) -> dict[str, Any]:
        return self.coordinator.data.thermostats.get(self._device.id) or {}

    @property
    def _state(self) -> dict[str, Any]:
        return self._node.get("state") or {}

    @property
    def hvac_modes(self) -> list[HVACMode]:
        modes = [HVACMode.OFF]
        for mode in self._node.get("modes") or []:
            hvac = _MODE_TO_HVAC.get(mode.get("name"))
            if hvac and hvac not in modes:
                modes.append(hvac)
        if len(modes) == 1:
            modes.append(HVACMode.HEAT)
        return modes

    @property
    def hvac_mode(self) -> HVACMode:
        if str(self._state.get("onOff")).upper() == "OFF":
            return HVACMode.OFF
        return _MODE_TO_HVAC.get(self._state.get("mode"), HVACMode.HEAT)

    @property
    def current_temperature(self) -> float | None:
        sensor = self._node.get("temperatureSensor") or {}
        return (sensor.get("measurement") or {}).get("value")

    @property
    def target_temperature(self) -> float | None:
        return self._state.get("comfortTemperature")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_set_thermostat_state(
            self._device.home_id,
            self._device.id,
            comfort_temperature=float(temperature),
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_thermostat_state(
                self._device.home_id, self._device.id, on_off="OFF"
            )
            return
        mode = _HVAC_TO_MODE.get(hvac_mode)
        await self.coordinator.async_set_thermostat_state(
            self._device.home_id, self._device.id, mode=mode, on_off="ON"
        )

    async def async_turn_on(self) -> None:
        await self.coordinator.async_set_thermostat_state(
            self._device.home_id, self._device.id, on_off="ON"
        )

    async def async_turn_off(self) -> None:
        await self.coordinator.async_set_thermostat_state(
            self._device.home_id, self._device.id, on_off="OFF"
        )
