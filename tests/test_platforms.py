"""Tests for binary_sensor, number, select, time, and button platforms."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.helpers import entity_registry as er

from custom_components.tibber_app.const import DOMAIN


def _eid(hass, entry, platform: str, suffix: str) -> str:
    reg = er.async_get(hass)
    uid = f"{entry.entry_id}_{suffix}"
    eid = reg.async_get_entity_id(platform, DOMAIN, uid)
    assert eid is not None, f"No entity for uid={uid!r}"
    return eid


# ---------------------------------------------------------------------------
# binary_sensor
# ---------------------------------------------------------------------------


class TestVehicleBinarySensors:
    async def test_online_is_on(self, hass, setup_integration):
        state = hass.states.get(
            _eid(hass, setup_integration, "binary_sensor", "ev-1_online")
        )
        assert state.state == "on"

    async def test_charging_is_off_when_idle(self, hass, setup_integration):
        """chargingStatus=IDLE → charging binary sensor is off."""
        state = hass.states.get(
            _eid(hass, setup_integration, "binary_sensor", "ev-1_charging")
        )
        assert state.state == "off"

    async def test_charging_is_on_when_charging(self, hass, setup_integration):
        """chargingStatus=CHARGING → charging binary sensor flips on."""
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.data.vehicles["ev-1"]["chargingStatus"] = "CHARGING"
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        state = hass.states.get(
            _eid(hass, setup_integration, "binary_sensor", "ev-1_charging")
        )
        assert state.state == "on"


class TestChargerBinarySensors:
    async def test_charger_online_is_on(self, hass, setup_integration):
        state = hass.states.get(
            _eid(hass, setup_integration, "binary_sensor", "charger-1_online")
        )
        assert state.state == "on"


class TestPulseBinarySensors:
    async def test_peak_exceeded_unknown_before_live(self, hass, setup_integration):
        state = hass.states.get(
            _eid(hass, setup_integration, "binary_sensor", "pulse-1_peak_exceeded")
        )
        assert state.state in ("unknown", "unavailable")

    async def test_peak_exceeded_off_when_normal(self, hass, setup_integration):
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.update_live("pulse-1", {"peakControlConsumptionState": "NORMAL"})
        await hass.async_block_till_done()

        state = hass.states.get(
            _eid(hass, setup_integration, "binary_sensor", "pulse-1_peak_exceeded")
        )
        assert state.state == "off"

    async def test_peak_exceeded_on_when_exceeded(self, hass, setup_integration):
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.update_live("pulse-1", {"peakControlConsumptionState": "EXCEEDED"})
        await hass.async_block_till_done()

        state = hass.states.get(
            _eid(hass, setup_integration, "binary_sensor", "pulse-1_peak_exceeded")
        )
        assert state.state == "on"


# ---------------------------------------------------------------------------
# number
# ---------------------------------------------------------------------------


class TestVehicleNumber:
    async def test_manual_soc_reads_battery_level(self, hass, setup_integration):
        """Manual SoC number reads from vehicle.battery.level in fixture (75)."""
        state = hass.states.get(
            _eid(hass, setup_integration, "number", "ev-1_manual_soc")
        )
        # API returns an integer; HA renders it without a decimal point.
        assert state.state == "75"

    async def test_manual_soc_unit_is_percent(self, hass, setup_integration):
        state = hass.states.get(
            _eid(hass, setup_integration, "number", "ev-1_manual_soc")
        )
        assert state.attributes["unit_of_measurement"] == "%"


class TestChargerNumbers:
    async def test_max_current_reads_user_settings(self, hass, setup_integration):
        """maxCurrentCharger=16 from fixture → state 16.0."""
        state = hass.states.get(
            _eid(hass, setup_integration, "number", "charger-1_max_current")
        )
        assert state.state == "16.0"

    async def test_main_fuse_reads_user_settings(self, hass, setup_integration):
        state = hass.states.get(
            _eid(hass, setup_integration, "number", "charger-1_main_fuse")
        )
        assert state.state == "25.0"

    async def test_offline_fallback_reads_user_settings(self, hass, setup_integration):
        state = hass.states.get(
            _eid(
                hass,
                setup_integration,
                "number",
                "charger-1_offline_fallback_current",
            )
        )
        assert state.state == "6.0"


class TestPeakLimitNumber:
    async def test_reads_consumption_limit(self, hass, setup_integration):
        """Peak limit reads peakControlData.consumptionLimit=5.0."""
        state = hass.states.get(
            _eid(hass, setup_integration, "number", "home-1_peak_limit")
        )
        assert state.state == "5.0"

    async def test_min_max_from_peak_control_data(self, hass, setup_integration):
        """Min/max are taken from peakControlData.lowerBound/upperBound."""
        state = hass.states.get(
            _eid(hass, setup_integration, "number", "home-1_peak_limit")
        )
        assert state.attributes["min"] == 2.0
        assert state.attributes["max"] == 10.0


# ---------------------------------------------------------------------------
# select
# ---------------------------------------------------------------------------


class TestPreferredVehicleSelect:
    async def test_current_option_is_preferred_vehicle(self, hass, setup_integration):
        """Preferred vehicle name is the current option."""
        state = hass.states.get(
            _eid(
                hass, setup_integration, "select", "charger-1_preferred_vehicle"
            )
        )
        assert state.state == "My Car"

    async def test_options_include_auto_and_vehicles(self, hass, setup_integration):
        state = hass.states.get(
            _eid(
                hass, setup_integration, "select", "charger-1_preferred_vehicle"
            )
        )
        options = state.attributes["options"]
        assert "Auto" in options
        assert "My Car" in options

    async def test_select_auto_sets_sentinel_id(self, hass, setup_integration):
        """Selecting 'Auto' writes the zero-UUID sentinel to the API."""
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.async_request_refresh = AsyncMock()

        mutation_mock = AsyncMock(return_value={})
        with patch.object(coordinator.client, "gql", new=mutation_mock):
            await hass.services.async_call(
                "select",
                "select_option",
                {
                    "entity_id": _eid(
                        hass,
                        setup_integration,
                        "select",
                        "charger-1_preferred_vehicle",
                    ),
                    "option": "Auto",
                },
                blocking=True,
            )

        mutation_mock.assert_called_once()
        _, variables = mutation_mock.call_args.args
        setting = variables["settings"][0]
        assert setting["key"] == "preferredVehicleId"
        assert setting["value"] == "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------


class TestDepartureTimeEntities:
    async def test_monday_departure_reads_user_settings(self, hass, setup_integration):
        """departure_monday reads '07:00' from userSettings → state '07:00:00'."""
        state = hass.states.get(
            _eid(hass, setup_integration, "time", "ev-1_departure_monday")
        )
        assert state is not None
        assert state.state == "07:00:00"

    async def test_all_seven_weekday_entities_created(
        self, hass, setup_integration
    ):
        """One time entity exists per weekday for the vehicle."""
        reg = er.async_get(hass)
        weekdays = (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
        for day in weekdays:
            uid = f"{setup_integration.entry_id}_ev-1_departure_{day}"
            assert reg.async_get_entity_id("time", DOMAIN, uid) is not None, (
                f"Missing entity for {day}"
            )

    async def test_set_departure_time_calls_mutation(self, hass, setup_integration):
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.async_request_refresh = AsyncMock()

        mutation_mock = AsyncMock(return_value={})
        with patch.object(coordinator.client, "gql", new=mutation_mock):
            await hass.services.async_call(
                "time",
                "set_value",
                {
                    "entity_id": _eid(
                        hass, setup_integration, "time", "ev-1_departure_monday"
                    ),
                    "time": "08:30:00",
                },
                blocking=True,
            )

        mutation_mock.assert_called_once()
        _, variables = mutation_mock.call_args.args
        assert variables["vehicleId"] == "ev-1"
        setting = variables["settings"][0]
        assert setting["key"] == "offline.vehicle.departureTimes.monday"
        assert setting["value"] == "08:30"

    async def test_connected_vehicle_uses_its_own_namespace(
        self, hass, connected_vehicle_poll_data, setup_integration
    ):
        """A connected vehicle reads and writes its "online." keys (issue #1)."""
        entity_id = _eid(hass, setup_integration, "time", "ev-1_departure_monday")
        assert hass.states.get(entity_id).state == "07:00:00"
        # Days without a time read as unknown rather than a bogus value.
        tuesday = _eid(hass, setup_integration, "time", "ev-1_departure_tuesday")
        assert hass.states.get(tuesday).state == "unknown"

        coordinator = setup_integration.runtime_data.coordinator
        coordinator.async_request_refresh = AsyncMock()

        mutation_mock = AsyncMock(return_value={})
        with patch.object(coordinator.client, "gql", new=mutation_mock):
            await hass.services.async_call(
                "time",
                "set_value",
                {"entity_id": entity_id, "time": "08:30:00"},
                blocking=True,
            )

        _, variables = mutation_mock.call_args.args
        setting = variables["settings"][0]
        assert setting["key"] == "online.vehicle.smartCharging.departureTimes.monday"
        assert setting["value"] == "08:30"


# ---------------------------------------------------------------------------
# button
# ---------------------------------------------------------------------------


class TestRefreshButton:
    async def test_button_exists(self, hass, setup_integration):
        eid = _eid(hass, setup_integration, "button", "home-1_refresh")
        assert hass.states.get(eid) is not None

    async def test_press_triggers_coordinator_refresh(self, hass, setup_integration):
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.async_request_refresh = AsyncMock()

        await hass.services.async_call(
            "button",
            "press",
            {
                "entity_id": _eid(
                    hass, setup_integration, "button", "home-1_refresh"
                )
            },
            blocking=True,
        )

        coordinator.async_request_refresh.assert_called_once()
