"""Tests for the TibberDataUpdateCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_app.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TOKEN,
    DOMAIN,
    GIZMO_ELECTRIC_VEHICLE,
    GIZMO_EV_CHARGER,
    GIZMO_REAL_TIME_METER,
)
from custom_components.tibber_app.coordinator import (
    TibberData,
    TibberDataUpdateCoordinator,
    TibberDevice,
    _alias,
)

_ENTRY_DATA = {CONF_EMAIL: "t@t.com", CONF_PASSWORD: "x", CONF_TOKEN: "y"}


def _make_coordinator(hass, discovery_data: dict, poll_data: dict):
    async def _gql(query: str, variables=None):
        if "gizmos" in query:
            return discovery_data
        if "gridRewardsHistory" in query:
            return {
                "me": {
                    "home": {
                        "gridRewardsHistory": {
                            "valuesFrom": None,
                            "valuesTo": None,
                        }
                    }
                }
            }
        return poll_data

    client = MagicMock()
    client.gql = AsyncMock(side_effect=_gql)
    entry = MockConfigEntry(domain=DOMAIN, data=_ENTRY_DATA, unique_id="acc-1")
    return TibberDataUpdateCoordinator(hass, entry, client)


class TestAlias:
    def test_replaces_hyphens_with_underscores(self):
        assert _alias("vehicle", "ev-1") == "vehicle_ev_1"
        assert _alias("home", "home-1") == "home_home_1"
        assert _alias("charger", "charger-1") == "charger_charger_1"

    def test_no_hyphens_unchanged(self):
        assert _alias("battery", "abc123") == "battery_abc123"


class TestDiscovery:
    async def test_parses_homes_and_devices(self, hass, discovery_data, poll_data):
        coord = _make_coordinator(hass, discovery_data, poll_data)
        await coord.async_discover()

        assert coord.home_titles == {"home-1": "My Home"}
        assert len(coord.devices) == 3

    async def test_ev_device_attributes(self, hass, discovery_data, poll_data):
        coord = _make_coordinator(hass, discovery_data, poll_data)
        await coord.async_discover()

        evs = coord.devices_of_type(GIZMO_ELECTRIC_VEHICLE)
        assert len(evs) == 1
        ev = evs[0]
        assert ev.id == "ev-1"
        assert ev.name == "My Car"
        assert ev.home_id == "home-1"
        assert ev.type == GIZMO_ELECTRIC_VEHICLE

    async def test_charger_device_attributes(self, hass, discovery_data, poll_data):
        coord = _make_coordinator(hass, discovery_data, poll_data)
        await coord.async_discover()

        chargers = coord.devices_of_type(GIZMO_EV_CHARGER)
        assert len(chargers) == 1
        assert chargers[0].id == "charger-1"

    async def test_pulse_device_discovered(self, hass, discovery_data, poll_data):
        coord = _make_coordinator(hass, discovery_data, poll_data)
        await coord.async_discover()

        pulses = coord.devices_of_type(GIZMO_REAL_TIME_METER)
        assert len(pulses) == 1
        assert pulses[0].id == "pulse-1"

    async def test_deduplicates_vehicle_across_homes(self, hass, poll_data):
        """Vehicle appearing under two homes is only registered once."""
        dup_discovery = {
            "me": {
                "homes": [
                    {
                        "id": "home-1",
                        "title": "Home 1",
                        "gizmos": [
                            {
                                "id": "ev-1",
                                "type": GIZMO_ELECTRIC_VEHICLE,
                                "title": "Car",
                                "gizmos": None,
                            }
                        ],
                    },
                    {
                        "id": "home-2",
                        "title": "Home 2",
                        "gizmos": [
                            {
                                "id": "ev-1",
                                "type": GIZMO_ELECTRIC_VEHICLE,
                                "title": "Car",
                                "gizmos": None,
                            }
                        ],
                    },
                ]
            }
        }
        coord = _make_coordinator(hass, dup_discovery, poll_data)
        await coord.async_discover()

        evs = coord.devices_of_type(GIZMO_ELECTRIC_VEHICLE)
        assert len(evs) == 1
        # First sighting (home-1) wins.
        assert evs[0].home_id == "home-1"

    async def test_gizmo_group_flattened(self, hass, poll_data):
        """GizmoGroup members are flattened into the device list."""
        grouped_discovery = {
            "me": {
                "homes": [
                    {
                        "id": "home-1",
                        "title": "Home 1",
                        "gizmos": [
                            {
                                "gizmos": [
                                    {
                                        "id": "ev-1",
                                        "type": GIZMO_ELECTRIC_VEHICLE,
                                        "title": "Car",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        }
        coord = _make_coordinator(hass, grouped_discovery, poll_data)
        await coord.async_discover()

        evs = coord.devices_of_type(GIZMO_ELECTRIC_VEHICLE)
        assert len(evs) == 1
        assert evs[0].id == "ev-1"


class TestParse:
    def _coord_with_devices(self, hass):
        """Pre-built coordinator with devices already set (bypasses discovery)."""
        client = MagicMock()
        entry = MockConfigEntry(domain=DOMAIN, data=_ENTRY_DATA, unique_id="acc-1")
        coord = TibberDataUpdateCoordinator(hass, entry, client)
        coord.home_titles = {"home-1": "My Home"}
        coord.devices = [
            TibberDevice(
                id="ev-1", name="My Car", type=GIZMO_ELECTRIC_VEHICLE, home_id="home-1"
            ),
            TibberDevice(
                id="charger-1",
                name="My Charger",
                type=GIZMO_EV_CHARGER,
                home_id="home-1",
            ),
            TibberDevice(
                id="pulse-1",
                name="Pulse",
                type=GIZMO_REAL_TIME_METER,
                home_id="home-1",
            ),
        ]
        return coord

    def test_vehicle_data_extracted(self, hass, poll_data):
        coord = self._coord_with_devices(hass)
        data = coord._parse(poll_data)

        assert "ev-1" in data.vehicles
        vehicle = data.vehicles["ev-1"]
        assert vehicle["battery"]["level"] == 75
        assert vehicle["battery"]["estimatedRange"] == 200
        assert vehicle["chargingStatus"] == "IDLE"
        assert vehicle["smartChargingStatus"] == "SMART_CHARGING"

    def test_charger_data_extracted(self, hass, poll_data):
        coord = self._coord_with_devices(hass)
        data = coord._parse(poll_data)

        assert "charger-1" in data.chargers
        charger = data.chargers["charger-1"]
        assert charger["chargingStatus"] == "READY"
        vehicles = charger["vehicles"]
        assert len(vehicles) == 1
        assert vehicles[0]["isPreferred"] is True

    def test_home_data_extracted(self, hass, poll_data):
        coord = self._coord_with_devices(hass)
        data = coord._parse(poll_data)

        assert "home-1" in data.homes
        home = data.homes["home-1"]
        assert home["title"] == "My Home"
        assert home["consumption"]["consumption"] == 150.0
        assert home["consumption"]["currency"] == "NOK"
        assert home["price"]["hourly"]["currency"] == "NOK"

    def test_pulse_not_in_polled_data(self, hass, poll_data):
        """Pulse data comes from WebSocket, not the poll query."""
        coord = self._coord_with_devices(hass)
        data = coord._parse(poll_data)
        # live starts empty until WS delivers a frame
        assert data.live == {}

    def test_live_data_preserved_across_parse(self, hass, poll_data):
        coord = self._coord_with_devices(hass)
        coord._live = {"pulse-1": {"power": 500.0}}
        data = coord._parse(poll_data)
        assert data.live["pulse-1"]["power"] == 500.0


class TestLiveUpdate:
    def _coord_with_data(self, hass, poll_data):
        """Coordinator that has already completed its first poll."""
        client = MagicMock()
        entry = MockConfigEntry(domain=DOMAIN, data=_ENTRY_DATA, unique_id="acc-1")
        coord = TibberDataUpdateCoordinator(hass, entry, client)
        coord.data = TibberData()
        coord.home_titles = {"home-1": "My Home"}
        coord.devices = []
        return coord

    def test_update_live_stores_measurement(self, hass, poll_data):
        coord = self._coord_with_data(hass, poll_data)
        coord.update_live("pulse-1", {"power": 1234.5})
        assert coord.data.live["pulse-1"]["power"] == 1234.5
        assert coord._live["pulse-1"]["power"] == 1234.5

    def test_update_live_before_first_poll_buffered(self, hass, poll_data):
        """Live updates received before the first poll are buffered in _live."""
        client = MagicMock()
        entry = MockConfigEntry(domain=DOMAIN, data=_ENTRY_DATA, unique_id="acc-1")
        coord = TibberDataUpdateCoordinator(hass, entry, client)
        # data is None until first poll completes
        assert coord.data is None

        coord.update_live("pulse-1", {"power": 999.0})
        assert coord._live["pulse-1"]["power"] == 999.0

    def test_update_battery_live_stores_state(self, hass, poll_data):
        coord = self._coord_with_data(hass, poll_data)
        coord.update_battery_live("bat-1", {"stateOfCharge": 88})
        assert coord.data.battery_live["bat-1"]["stateOfCharge"] == 88
