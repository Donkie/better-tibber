"""Tests for the Tibber app config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_app.api import TibberApiError, TibberAuthError
from custom_components.tibber_app.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TOKEN,
    DOMAIN,
)

VALID_USER_INPUT = {CONF_EMAIL: "user@test.com", CONF_PASSWORD: "correct_pass"}


def _make_client(*, account_id: str = "acc-1", token: str = "tok123", raises=None):
    """Build a mock TibberAppClient."""
    client = MagicMock()
    if raises:
        client.login = AsyncMock(side_effect=raises)
    else:
        client.login = AsyncMock(return_value=token)
        client.gql = AsyncMock(return_value={"me": {"id": account_id}})
    return client


async def test_user_step_shows_form(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result.get("errors")


async def test_user_step_creates_entry(hass):
    with patch(
        "custom_components.tibber_app.config_flow.TibberAppClient",
        return_value=_make_client(account_id="acc-1", token="tok123"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@test.com"
    assert result["data"][CONF_EMAIL] == "user@test.com"
    assert result["data"][CONF_PASSWORD] == "correct_pass"
    assert result["data"][CONF_TOKEN] == "tok123"


async def test_user_step_invalid_auth(hass):
    with patch(
        "custom_components.tibber_app.config_flow.TibberAppClient",
        return_value=_make_client(raises=TibberAuthError("bad creds")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_step_cannot_connect(hass):
    with patch(
        "custom_components.tibber_app.config_flow.TibberAppClient",
        return_value=_make_client(raises=TibberApiError("timeout")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_step_already_configured(hass):
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="acc-1",
        data={CONF_EMAIL: "user@test.com", CONF_PASSWORD: "x", CONF_TOKEN: "y"},
    )
    existing.add_to_hass(hass)

    with patch(
        "custom_components.tibber_app.config_flow.TibberAppClient",
        return_value=_make_client(account_id="acc-1"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_shows_form(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="acc-1",
        data={CONF_EMAIL: "user@test.com", CONF_PASSWORD: "old", CONF_TOKEN: "old_tok"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_success(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="acc-1",
        data={CONF_EMAIL: "user@test.com", CONF_PASSWORD: "old", CONF_TOKEN: "old_tok"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)

    with patch(
        "custom_components.tibber_app.config_flow.TibberAppClient",
        return_value=_make_client(account_id="acc-1", token="new_tok"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new_pass"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "new_tok"
    assert entry.data[CONF_PASSWORD] == "new_pass"
