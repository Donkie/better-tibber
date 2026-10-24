"""Tests for the smart-charging plan entities (issue #5)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.tibber_app.const import DOMAIN
from custom_components.tibber_app.coordinator import charging_windows


def _period(start: datetime, minutes: int, from_soc, to_soc, energy, cost=0.1):
    return {
        "startAt": start.isoformat(),
        "stopAt": (start + timedelta(minutes=minutes)).isoformat(),
        "fromStateOfCharge": from_soc,
        "toStateOfCharge": to_soc,
        "energy": energy,
        "cost": cost,
        "gridReward": 0,
    }


def _vehicle(*days):
    return {"charging": {"currency": "SEK", "days": [{"periods": p} for p in days]}}


class TestChargingWindows:
    NOW = datetime(2026, 10, 25, 12, 0, tzinfo=dt_util.UTC)

    def test_merges_back_to_back_and_drops_finished(self):
        now = self.NOW
        vehicle = _vehicle(
            # Already finished; must not show up.
            [_period(now - timedelta(hours=10), 60, 9, 18, 2.0)],
            [
                # Out of order on purpose: the backend's order isn't relied on.
                _period(now + timedelta(minutes=105), 15, 89, 91, 0.5),
                _period(now + timedelta(minutes=60), 45, 82, 87, 1.4),
                _period(now + timedelta(hours=10), 30, 91, 94, 0.9),
            ],
        )
        windows = charging_windows(vehicle, now)

        assert [(w["start"], w["end"]) for w in windows] == [
            (now + timedelta(minutes=60), now + timedelta(minutes=120)),
            (now + timedelta(hours=10), now + timedelta(hours=10, minutes=30)),
        ]
        assert windows[0]["from_soc"] == 82
        assert windows[0]["to_soc"] == 91
        assert windows[0]["energy"] == pytest.approx(1.9)

    def test_no_plan(self):
        # Unplugged vehicles report periods: null; empty days report [].
        assert charging_windows(_vehicle(None, []), self.NOW) == []
        assert charging_windows({"charging": {"days": None}}, self.NOW) == []
        assert charging_windows({}, self.NOW) == []


@pytest.fixture
def poll_data(poll_data: dict) -> dict:
    """The fixture vehicle mid-way through a window, with one more planned."""
    now = dt_util.utcnow()
    poll_data["me"]["vehicle_ev_1"]["charging"] |= {
        "currency": "SEK",
        "days": [
            {
                "periods": [
                    _period(now - timedelta(minutes=30), 60, 40, 50, 5.0, 1.0),
                    _period(now + timedelta(hours=2), 60, 50, 60, 4.0, 0.5),
                ]
            }
        ],
    }
    return poll_data


def _state(hass, entry, platform: str, key: str):
    uid = f"{entry.entry_id}_ev-1_{key}"
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, uid)
    assert eid is not None, f"No entity for uid={uid!r}"
    return hass.states.get(eid)


async def test_plan_entities(hass, setup_integration):
    entry = setup_integration

    planned = _state(hass, entry, "binary_sensor", "charging_planned")
    assert planned.state == "on"
    assert planned.attributes["next_start"] is not None
    assert len(planned.attributes["windows"]) == 2

    calendar = _state(hass, entry, "calendar", "charging_plan")
    assert calendar.state == "on"
    assert calendar.attributes["message"] == "Charging 40% → 50%"

    assert float(_state(hass, entry, "sensor", "planned_energy").state) == 9.0
    cost = _state(hass, entry, "sensor", "planned_cost")
    assert float(cost.state) == 1.5
    assert cost.attributes["unit_of_measurement"] == "SEK"
    next_start = dt_util.parse_datetime(
        _state(hass, entry, "sensor", "next_planned_charge").state
    )
    assert next_start > dt_util.utcnow() + timedelta(hours=1)
