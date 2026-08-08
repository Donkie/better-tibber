"""Shared test fixtures for the tibber_app integration tests."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from aiohttp import ClientResponse
from aioresponses.core import RequestMatch
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_app.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TOKEN,
    DOMAIN,
)

# aiohttp>=3.14 added a required `stream_writer` kwarg to ClientResponse.__init__,
# which aioresponses (still 0.7.9 on PyPI) doesn't supply yet — every mocked
# response raises TypeError. Upstream fix is stuck in an unmerged PR
# (https://github.com/pnuckowski/aioresponses/pull/288); rather than depend on an
# unreleased fork, shim it here. Feature-detected, so this is a no-op once either
# side ships a real fix.
if "stream_writer" in inspect.signature(ClientResponse).parameters:

    class _StreamWriterCompatResponse(ClientResponse):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.setdefault("stream_writer", Mock(output_size=0))
            super().__init__(*args, **kwargs)

    _original_build_response = RequestMatch._build_response

    def _build_response_with_stream_writer(self, *args, **kwargs):
        # aioresponses always passes response_class=<None-or-explicit> by keyword
        # (see RequestMatch.build_response), so setdefault() would never fire.
        if kwargs.get("response_class") is None:
            kwargs["response_class"] = _StreamWriterCompatResponse
        return _original_build_response(self, *args, **kwargs)

    RequestMatch._build_response = _build_response_with_stream_writer


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
