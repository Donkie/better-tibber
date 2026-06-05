"""Integration-level tests: setup, unload, and auth-failure → reauth."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.tibber_app import TibberRuntimeData
from custom_components.tibber_app.api import TibberAuthError


class TestSetupAndUnload:
    async def test_entry_is_loaded(self, hass, setup_integration):
        """Config entry reaches LOADED state after a successful setup."""
        assert setup_integration.state is ConfigEntryState.LOADED

    async def test_platforms_are_forwarded(self, hass, setup_integration):
        """At least the sensor platform is forwarded (entities exist)."""
        reg = er.async_get(hass)
        sensor_entries = [
            e for e in reg.entities.values() if e.domain == "sensor"
        ]
        assert len(sensor_entries) > 0

    async def test_unload_succeeds(self, hass, setup_integration):
        """Entry can be unloaded cleanly without errors."""
        result = await hass.config_entries.async_unload(
            setup_integration.entry_id
        )
        assert result is True
        assert setup_integration.state is ConfigEntryState.NOT_LOADED

    async def test_runtime_data_has_coordinator_and_live(
        self, hass, setup_integration
    ):
        assert isinstance(setup_integration.runtime_data, TibberRuntimeData)
        assert setup_integration.runtime_data.coordinator is not None
        assert setup_integration.runtime_data.live is not None


class TestAuthFailureReauth:
    async def test_poll_auth_error_starts_reauth_flow(
        self, hass, setup_integration
    ):
        """When a poll raises TibberAuthError, HA starts a reauth flow."""
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.client.gql = AsyncMock(
            side_effect=TibberAuthError("token expired")
        )

        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

        flows = hass.config_entries.flow.async_progress()
        reauth = [
            f
            for f in flows
            if f["context"]["source"] == config_entries.SOURCE_REAUTH
        ]
        assert len(reauth) == 1
        assert reauth[0]["context"]["entry_id"] == setup_integration.entry_id

    async def test_entry_state_after_auth_failure(
        self, hass, setup_integration
    ):
        """Entry stays LOADED (so poll can resume once reauth completes)."""
        coordinator = setup_integration.runtime_data.coordinator
        coordinator.client.gql = AsyncMock(
            side_effect=TibberAuthError("token expired")
        )

        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

        assert setup_integration.state is ConfigEntryState.LOADED
