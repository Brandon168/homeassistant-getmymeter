"""Config flow for GetMyMeter."""

from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_TOKEN
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GetMyMeterApi, GetMyMeterApiError, GetMyMeterAuthError
from .const import (
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    DEFAULT_CHANNEL,
    DEFAULT_COMPANY_ID,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
)
from .identity import stable_entry_unique_id


class GetMyMeterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a GetMyMeter config flow."""

    VERSION = 1

    async def _async_validate(self, data: Mapping[str, object]) -> None:
        """Validate the supplied token with one read-only daily request."""
        api = GetMyMeterApi(async_get_clientsession(self.hass), data)
        await api.async_fetch_bucket("d")

    @staticmethod
    def _unique_id(data: Mapping[str, object]) -> str:
        """Build a stable, non-identifying meter-channel ID."""
        return stable_entry_unique_id(data)

    @staticmethod
    def _schema() -> vol.Schema:
        """Return the user setup schema."""
        return vol.Schema(
            {
                vol.Required(CONF_COMPANY_ID, default=DEFAULT_COMPANY_ID): str,
                vol.Required(CONF_ACCOUNT): str,
                vol.Required(CONF_CHANNEL, default=DEFAULT_CHANNEL): str,
                vol.Required(CONF_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD,
                        autocomplete="current-password",
                    )
                ),
            }
        )

    @staticmethod
    def _errors_for_exception(error: Exception) -> str:
        """Map an API failure to a secret-free flow error key."""
        if isinstance(error, GetMyMeterAuthError):
            return ERROR_INVALID_AUTH
        if isinstance(error, GetMyMeterApiError):
            return ERROR_CANNOT_CONNECT
        return ERROR_UNKNOWN

    async def _async_validate_and_get_errors(
        self, data: Mapping[str, object]
    ) -> str | None:
        """Validate data and return a translated error key when needed."""
        try:
            await self._async_validate(data)
        except Exception as err:  # noqa: BLE001
            return self._errors_for_exception(err)
        return None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a user-initiated setup flow."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await self._async_validate_and_get_errors(user_input):
                errors["base"] = error
            else:
                await self.async_set_unique_id(self._unique_id(user_input))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="GetMyMeter",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(),
            errors=errors,
        )

    async def async_step_reauth(
        self, _entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a token-expiry reauthentication request."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Accept a replacement portal token."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN]}
            if error := await self._async_validate_and_get_errors(data):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_TOKEN: user_input[CONF_TOKEN]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the portal identity and validate the supplied token."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            if error := await self._async_validate_and_get_errors(data):
                errors["base"] = error
            else:
                unique_id = stable_entry_unique_id(data)
                await self.async_set_unique_id(unique_id)
                if unique_id != entry.unique_id:
                    self._abort_if_unique_id_configured()
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    data=data,
                )

        suggested = {
            key: entry.data[key]
            for key in (CONF_COMPANY_ID, CONF_ACCOUNT, CONF_CHANNEL)
            if key in entry.data
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(self._schema(), suggested),
            errors=errors,
        )
