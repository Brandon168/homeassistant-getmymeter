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


class GetMyMeterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a GetMyMeter config flow."""

    VERSION = 1

    async def _async_validate(self, data: Mapping[str, object]) -> None:
        """Validate the supplied token with one read-only daily request."""
        api = GetMyMeterApi(async_get_clientsession(self.hass), data)
        await api.async_fetch_bucket("d")

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

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a user-initiated setup flow."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._async_validate(user_input)
            except GetMyMeterAuthError:
                errors["base"] = ERROR_INVALID_AUTH
            except GetMyMeterApiError:
                errors["base"] = ERROR_CANNOT_CONNECT
            except Exception:  # noqa: BLE001
                errors["base"] = ERROR_UNKNOWN
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

    @staticmethod
    def _unique_id(data: Mapping[str, object]) -> str:
        """Build a stable identifier for one portal meter channel."""
        return "|".join(
            str(data[key]) for key in (CONF_COMPANY_ID, CONF_ACCOUNT, CONF_CHANNEL)
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
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
            try:
                await self._async_validate(data)
            except GetMyMeterAuthError:
                errors["base"] = ERROR_INVALID_AUTH
            except GetMyMeterApiError:
                errors["base"] = ERROR_CANNOT_CONNECT
            except Exception:  # noqa: BLE001
                errors["base"] = ERROR_UNKNOWN
            else:
                return self.async_update_reload_and_abort(entry, data=data)

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
