"""Shared test fixtures for the tibber_app integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_app.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TOKEN,
    DOMAIN,
)


def load_fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for every test in this suite."""


@pytest.fixture
def discovery_data() -> dict:
    return load_fixture("discovery.json")


@pytest.fixture
def poll_data() -> dict:
    return load_fixture("poll.json")


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_EMAIL: "test@example.com",
            CONF_PASSWORD: "secret",
            CONF_TOKEN: "token123",
        },
        unique_id="account-id-1",
    )


def _gql_dispatcher(discovery_data: dict, poll_data: dict):
    """Build a side_effect function that routes GQL calls to the right fixture."""

    async def _gql(query: str, variables: dict | None = None) -> dict:
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

    return _gql


@pytest.fixture
def mock_client(discovery_data: dict, poll_data: dict) -> MagicMock:
    """A TibberAppClient mock that returns fixture data."""
    client = MagicMock()
    client.login = AsyncMock(return_value="token123")
    client.gql = AsyncMock(side_effect=_gql_dispatcher(discovery_data, poll_data))
    return client


@pytest.fixture
async def setup_integration(
    hass, config_entry: MockConfigEntry, mock_client: MagicMock
) -> MockConfigEntry:
    """Load the integration with mocked API calls; yield the config entry."""
    with (
        patch(
            "custom_components.tibber_app.TibberAppClient",
            return_value=mock_client,
        ),
        patch("custom_components.tibber_app.LiveMeterManager") as mock_lm_class,
    ):
        lm = MagicMock()
        lm.start = MagicMock()
        lm.async_stop = AsyncMock()
        mock_lm_class.return_value = lm

        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        yield config_entry
