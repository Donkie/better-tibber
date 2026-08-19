"""Tests for the Tibber app switch platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.tibber_app.const import DOMAIN

_SMART_CHARGING_SUFFIX = "smartCharging.isEnabled"


def _entity_id(hass, setup_integration, platform: str, unique_id_suffix: str) -> str:
    reg = er.async_get(hass)
    uid = f"{setup_integration.entry_id}_{unique_id_suffix}"
    eid = reg.async_get_entity_id(platform, DOMAIN, uid)
    assert eid is not None, f"Entity not found for unique_id={uid!r}"
    return eid


@pytest.fixture
def no_smart_charging_poll_data(poll_data: dict) -> dict:
    """Poll data for a vehicle that exposes no smart-charging toggle at all."""
    settings = poll_data["me"]["vehicle_ev_1"]["userSettings"]
    poll_data["me"]["vehicle_ev_1"]["userSettings"] = [
        s for s in settings if not s["key"].endswith(_SMART_CHARGING_SUFFIX)
    ]
    return poll_data


class TestSmartChargingSwitch:
    async def test_reads_enabled_from_user_settings(self, hass, setup_integration):
        """Smart charging switch is ON when userSettings reports 'true'."""
        entity_id = _entity_id(
            hass, setup_integration, "switch", "ev-1_smart_charging"
        )
        state = hass.states.get(entity_id)
        assert state.state == "on"

    async def test_turn_off_calls_set_vehicle_setting(self, hass, setup_integration):
        """Turning off smart charging calls setVehicleSettings with value=False."""
        entity_id = _entity_id(
            hass, setup_integration, "switch", "ev-1_smart_charging"
        )
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.async_request_refresh = AsyncMock()

        mutation_mock = AsyncMock(return_value={})
        with patch.object(coordinator.client, "gql", new=mutation_mock):
            await hass.services.async_call(
                "switch", "turn_off", {"entity_id": entity_id}, blocking=True
            )

        # The mock is checked after the context (patch restores original),
        # so we kept our own reference to the AsyncMock.
        mutation_mock.assert_called_once()
        _, variables = mutation_mock.call_args.args
        assert variables["vehicleId"] == "ev-1"
        key = variables["settings"][0]["key"]
        assert key == "offline.vehicle.smartCharging.isEnabled"
        assert variables["settings"][0]["value"] is False

    async def test_writes_the_key_the_vehicle_exposes(
        self, hass, connected_vehicle_poll_data, setup_integration
    ):
        """A connected vehicle is written via its "online." setting key (issue #1)."""
        entity_id = _entity_id(
            hass, setup_integration, "switch", "ev-1_smart_charging"
        )
        assert hass.states.get(entity_id).state == "on"

        coordinator = setup_integration.runtime_data.coordinator
        coordinator.async_request_refresh = AsyncMock()

        mutation_mock = AsyncMock(return_value={})
        with patch.object(coordinator.client, "gql", new=mutation_mock):
            await hass.services.async_call(
                "switch", "turn_off", {"entity_id": entity_id}, blocking=True
            )

        _, variables = mutation_mock.call_args.args
        key = variables["settings"][0]["key"]
        assert key == "online.vehicle.smartCharging.isEnabled"

    async def test_not_created_without_the_setting(
        self, hass, no_smart_charging_poll_data, setup_integration
    ):
        """No switch is created for a vehicle that has no smart-charging setting."""
        reg = er.async_get(hass)
        uid = f"{setup_integration.entry_id}_ev-1_smart_charging"
        assert reg.async_get_entity_id("switch", DOMAIN, uid) is None


class TestChargerSwitches:
    async def test_cable_lock_state_from_user_settings(self, hass, setup_integration):
        """Cable lock reads its state from charger userSettings (value='false')."""
        entity_id = _entity_id(
            hass, setup_integration, "switch", "charger-1_cable_lock"
        )
        state = hass.states.get(entity_id)
        assert state.state == "off"

    async def test_load_balancing_state_from_user_settings(
        self, hass, setup_integration
    ):
        """Load balancing reads its state from charger userSettings (value='true')."""
        entity_id = _entity_id(
            hass, setup_integration, "switch", "charger-1_load_balancing"
        )
        state = hass.states.get(entity_id)
        assert state.state == "on"


class TestAwayModeSwitch:
    async def test_initial_state_is_off(self, hass, setup_integration):
        """Away mode starts as OFF (optimistic, no server read-back)."""
        entity_id = _entity_id(
            hass, setup_integration, "switch", "home-1_away_mode"
        )
        state = hass.states.get(entity_id)
        assert state.state == "off"

    async def test_turn_on_sets_optimistic_state(self, hass, setup_integration):
        """Turning away mode ON immediately reflects as 'on' (assumed_state)."""
        entity_id = _entity_id(
            hass, setup_integration, "switch", "home-1_away_mode"
        )
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.async_request_refresh = AsyncMock()

        with patch.object(coordinator.client, "gql", new=AsyncMock(return_value={})):
            await hass.services.async_call(
                "switch", "turn_on", {"entity_id": entity_id}, blocking=True
            )

        state = hass.states.get(entity_id)
        assert state.state == "on"


class TestPeakControlSwitch:
    async def test_initial_state_is_off(self, hass, setup_integration):
        """Peak control switch reflects peakControlData.isActive=false."""
        entity_id = _entity_id(
            hass, setup_integration, "switch", "home-1_peak_control"
        )
        state = hass.states.get(entity_id)
        assert state.state == "off"
