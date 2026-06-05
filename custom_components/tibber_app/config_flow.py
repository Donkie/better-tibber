"""Config flow for the Tibber app integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TibberApiError, TibberAppClient, TibberAuthError
from .const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class TibberAppConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the email/password login flow."""

    VERSION = 1

    async def _validate(
        self, email: str, password: str
    ) -> tuple[str | None, str | None, dict[str, str]]:
        """Return (account_id, token, errors) after attempting a login."""
        session = async_get_clientsession(self.hass)
        client = TibberAppClient(session, email, password)
        try:
            token = await client.login()
            data = await client.gql("{ me { id } }")
        except TibberAuthError:
            return None, None, {"base": "invalid_auth"}
        except TibberApiError:
            return None, None, {"base": "cannot_connect"}
        return data.get("me", {}).get("id"), token, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            account_id, token, errors = await self._validate(
                email, user_input[CONF_PASSWORD]
            )
            if not errors:
                await self.async_set_unique_id(account_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=email,
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_TOKEN: token,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered when the stored credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            email = entry.data[CONF_EMAIL]
            account_id, token, errors = await self._validate(
                email, user_input[CONF_PASSWORD]
            )
            if not errors:
                await self.async_set_unique_id(account_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_TOKEN: token,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            errors=errors,
        )
