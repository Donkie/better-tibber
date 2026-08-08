"""Tests for the Tibber app sensor platform."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.tibber_app.const import DOMAIN
from custom_components.tibber_app.sensor import _parse_departure


def _entity_id(hass, setup_integration, platform: str, unique_id_suffix: str) -> str:
    """Look up entity_id by unique_id suffix (entry_id + suffix)."""
    reg = er.async_get(hass)
    uid = f"{setup_integration.entry_id}_{unique_id_suffix}"
    eid = reg.async_get_entity_id(platform, DOMAIN, uid)
    assert eid is not None, f"Entity not found for unique_id={uid!r}"
    return eid


class TestVehicleSensors:
    async def test_battery_level_state(self, hass, setup_integration):
        entity_id = _entity_id(hass, setup_integration, "sensor", "ev-1_battery_level")
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "75"

    async def test_battery_level_unit(self, hass, setup_integration):
        entity_id = _entity_id(hass, setup_integration, "sensor", "ev-1_battery_level")
        state = hass.states.get(entity_id)
        assert state.attributes["unit_of_measurement"] == "%"

    async def test_estimated_range_state(self, hass, setup_integration):
        entity_id = _entity_id(hass, setup_integration, "sensor", "ev-1_range")
        state = hass.states.get(entity_id)
        assert state.state == "200"

    async def test_charging_status_state(self, hass, setup_integration):
        entity_id = _entity_id(
            hass, setup_integration, "sensor", "ev-1_charging_status"
        )
        state = hass.states.get(entity_id)
        assert state.state == "IDLE"

    async def test_session_energy_state(self, hass, setup_integration):
        entity_id = _entity_id(hass, setup_integration, "sensor", "ev-1_session_energy")
        state = hass.states.get(entity_id)
        assert state.state == "12.5"


class TestTargetDeparture:
    """The API echoes the current time when no departure is scheduled."""

    def test_future_time_is_kept(self):
        value = (dt_util.utcnow() + timedelta(hours=5)).isoformat()
        assert _parse_departure(value) == dt_util.parse_datetime(value)

    def test_current_time_is_dropped(self):
        assert _parse_departure(dt_util.utcnow().isoformat()) is None

    def test_past_time_is_dropped(self):
        stale = (dt_util.utcnow() - timedelta(hours=3)).isoformat()
        assert _parse_departure(stale) is None

    def test_missing_value_is_dropped(self):
        assert _parse_departure(None) is None


class TestChargerSensors:
    async def test_charging_status_ready(self, hass, setup_integration):
        entity_id = _entity_id(
            hass, setup_integration, "sensor", "charger-1_charging_status"
        )
        state = hass.states.get(entity_id)
        assert state.state == "READY"

    async def test_active_vehicle_name(self, hass, setup_integration):
        """active_vehicle reports the name of the preferred vehicle."""
        entity_id = _entity_id(
            hass, setup_integration, "sensor", "charger-1_active_vehicle"
        )
        state = hass.states.get(entity_id)
        assert state.state == "My Car"


class TestHomeSensors:
    async def test_price_sensor_value(self, hass, setup_integration):
        """Price sensor returns the total from the fixture entry."""
        entity_id = _entity_id(
            hass, setup_integration, "sensor", "home-1_electricity_price"
        )
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "1.23"

    async def test_price_sensor_unit(self, hass, setup_integration):
        entity_id = _entity_id(
            hass, setup_integration, "sensor", "home-1_electricity_price"
        )
        state = hass.states.get(entity_id)
        assert state.attributes.get("unit_of_measurement") == "NOK/kWh"

    async def test_consumption_month_state(self, hass, setup_integration):
        entity_id = _entity_id(
            hass, setup_integration, "sensor", "home-1_consumption_month"
        )
        state = hass.states.get(entity_id)
        assert state.state == "150.0"

    async def test_cost_month_state(self, hass, setup_integration):
        entity_id = _entity_id(hass, setup_integration, "sensor", "home-1_cost_month")
        state = hass.states.get(entity_id)
        assert state.state == "185.0"

    async def test_cost_month_currency(self, hass, setup_integration):
        entity_id = _entity_id(hass, setup_integration, "sensor", "home-1_cost_month")
        state = hass.states.get(entity_id)
        assert state.attributes.get("unit_of_measurement") == "NOK"


class TestPulseSensors:
    async def test_power_sensor_unknown_before_live_data(self, hass, setup_integration):
        """Power sensor is unavailable until the first WS frame arrives."""
        entity_id = _entity_id(hass, setup_integration, "sensor", "pulse-1_power")
        state = hass.states.get(entity_id)
        # No live data yet — state should be unknown or unavailable.
        assert state.state in (STATE_UNKNOWN, "unavailable", "unknown")

    async def test_power_sensor_updates_from_live(self, hass, setup_integration):
        """Coordinator.update_live() pushes a new state to the power sensor."""
        coordinator = setup_integration.runtime_data.coordinator
        entity_id = _entity_id(hass, setup_integration, "sensor", "pulse-1_power")

        coordinator.update_live("pulse-1", {"power": 1500.0, "currency": "NOK"})
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.state == "1500.0"

    async def test_accumulated_consumption_updates_from_live(
        self, hass, setup_integration
    ):
        coordinator = setup_integration.runtime_data.coordinator
        entity_id = _entity_id(
            hass,
            setup_integration,
            "sensor",
            "pulse-1_accumulated_consumption",
        )

        coordinator.update_live(
            "pulse-1",
            {"power": 0, "accumulatedConsumption": 5.23, "currency": "NOK"},
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.state == "5.23"

    async def test_accumulated_cost_currency_from_live(self, hass, setup_integration):
        """accumulated_cost unit is taken from the live measurement's currency field."""
        coordinator = setup_integration.runtime_data.coordinator
        entity_id = _entity_id(
            hass, setup_integration, "sensor", "pulse-1_accumulated_cost"
        )

        coordinator.update_live(
            "pulse-1",
            {"accumulatedCost": 12.5, "currency": "SEK"},
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state.state == "12.5"
        assert state.attributes.get("unit_of_measurement") == "SEK"
