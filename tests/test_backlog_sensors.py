"""Tests for the live hour/peak sensors, monthly peaks and the charge-now button."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.tibber_app.const import DOMAIN
from custom_components.tibber_app.coordinator import monthly_peaks

CHARGE_NOW = "grpc.vehicle.startCharging:vehicle:charger"


def _eid(hass, entry, platform: str, suffix: str) -> str:
    eid = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{suffix}"
    )
    assert eid is not None, suffix
    return eid


def _hour(start: str, kwh: float | None) -> dict:
    return {"from": start, "netConsumption": kwh}


class TestMonthlyPeaks:
    def test_one_peak_per_day_sorted(self):
        hours = [
            _hour("2026-11-01T17:00:00.000+01:00", 4.0),
            _hour("2026-11-01T18:00:00.000+01:00", 6.0),
            _hour("2026-11-02T08:00:00.000+01:00", 5.0),
            _hour("2026-11-03T08:00:00.000+01:00", None),
        ]
        assert monthly_peaks(hours) == [
            {"start": "2026-11-01T18:00:00+01:00", "consumption": 6.0},
            {"start": "2026-11-02T08:00:00+01:00", "consumption": 5.0},
        ]

    def test_capped_at_count(self):
        hours = [_hour(f"2026-11-{d:02d}T12:00:00+01:00", d) for d in range(1, 10)]
        peaks = monthly_peaks(hours, count=3)
        assert [p["consumption"] for p in peaks] == [9, 8, 7]


class TestLiveSensors:
    async def test_live_fields(self, hass, setup_integration):
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.update_live(
            "pulse-1",
            {
                "minPower": 672,
                "maxPower": 7604,
                "averagePower": 2378.9,
                "accumulatedConsumptionCurrentHour": 1.2,
                "estimatedAccumulatedConsumptionCurrentHour": 3.4,
                "peakControlConsumptionState": "ESTIMATE_CLOSE_TO_LIMIT",
                "effectiveHourlyConsumptionLimit": 4.5,
            },
        )
        await hass.async_block_till_done()

        def state(suffix):
            eid = _eid(hass, setup_integration, "sensor", f"pulse-1_{suffix}")
            return hass.states.get(eid).state

        assert state("min_power") == "672"
        assert state("max_power") == "7604"
        assert state("average_power") == "2378.9"
        assert state("consumption_this_hour") == "1.2"
        assert state("estimated_consumption_this_hour") == "3.4"
        assert state("peak_control_state") == "estimate_close_to_limit"
        assert state("effective_hourly_limit") == "4.5"

    async def test_unknown_peak_state_is_unknown(self, hass, setup_integration):
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.update_live("pulse-1", {"peakControlConsumptionState": "NEW"})
        await hass.async_block_till_done()
        eid = _eid(hass, setup_integration, "sensor", "pulse-1_peak_control_state")
        assert hass.states.get(eid).state == "unknown"


@pytest.fixture
def analysis_client(mock_client, poll_data):
    """Answer the consumption analysis query (gizmo consumption stays 150)."""
    dispatch = mock_client.gql.side_effect

    async def _gql(query, variables=None, *, partial_ok=False):
        if "consumptionAnalysisItems" in query:
            hours = [
                _hour("2026-11-01T18:00:00.000+01:00", 6.5),
                _hour("2026-11-02T08:00:00.000+01:00", 5.0),
            ]
            return {
                "me": {
                    "home": {
                        "month": [{"netConsumption": {"consumption": 1242.0671}}],
                        "days": [{"chart": {"items": hours}}],
                    }
                }
            }
        return await dispatch(query, variables, partial_ok=partial_ok)

    mock_client.gql.side_effect = _gql
    return mock_client


class TestConsumptionAnalysis:
    async def test_month_prefers_analysis(
        self, hass, analysis_client, setup_integration
    ):
        eid = _eid(hass, setup_integration, "sensor", "home-1_consumption_month")
        assert hass.states.get(eid).state == "1242.067"

    async def test_month_falls_back_to_gizmo(self, hass, setup_integration):
        eid = _eid(hass, setup_integration, "sensor", "home-1_consumption_month")
        assert hass.states.get(eid).state == "150.0"

    async def test_monthly_peak(self, hass, analysis_client, setup_integration):
        eid = _eid(hass, setup_integration, "sensor", "home-1_monthly_peak")
        state = hass.states.get(eid)
        assert state.state == "6.5"
        assert len(state.attributes["peaks"]) == 2


@pytest.fixture
def charge_now_poll_data(poll_data):
    poll_data["me"]["vehicle_ev_1"]["actionButtons"] = [
        {"enabled": True, "action": CHARGE_NOW}
    ]
    return poll_data


class TestChargeNowButton:
    async def test_unavailable_without_offer(self, hass, setup_integration):
        eid = _eid(hass, setup_integration, "button", "ev-1_charge_now")
        assert hass.states.get(eid).state == "unavailable"

    async def test_press_sends_action(
        self, hass, charge_now_poll_data, setup_integration
    ):
        eid = _eid(hass, setup_integration, "button", "ev-1_charge_now")
        assert hass.states.get(eid).state != "unavailable"

        coordinator = setup_integration.runtime_data.coordinator
        coordinator.async_request_refresh = AsyncMock()
        mutation = AsyncMock(return_value={})
        with patch.object(coordinator.client, "gql", new=mutation):
            await hass.services.async_call(
                "button", "press", {"entity_id": eid}, blocking=True
            )

        _, variables = mutation.call_args.args
        assert variables["vehicleId"] == "ev-1"
        assert variables["settings"] == [{"key": "action", "value": CHARGE_NOW}]

    async def test_resume_offered_while_suspended(
        self, hass, charge_now_poll_data, setup_integration
    ):
        """Only the offered action's button is available."""
        resume = "grpc.vehicle.enableSmartCharging:vehicle:other"
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.data.vehicles["ev-1"]["actionButtons"] = [
            {"enabled": True, "action": resume}
        ]
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        charge = _eid(hass, setup_integration, "button", "ev-1_charge_now")
        eid = _eid(hass, setup_integration, "button", "ev-1_resume_smart_charging")
        assert hass.states.get(charge).state == "unavailable"
        assert hass.states.get(eid).state != "unavailable"

    async def test_disabled_offer_is_ignored(
        self, hass, charge_now_poll_data, setup_integration
    ):
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.data.vehicles["ev-1"]["actionButtons"][0]["enabled"] = False
        button = hass.data["entity_components"]["button"].get_entity(
            _eid(hass, setup_integration, "button", "ev-1_charge_now")
        )
        with pytest.raises(HomeAssistantError):
            await button.async_press()
