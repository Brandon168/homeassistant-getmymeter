"""Config flow for GetMyMeter."""

from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    GetMyMeterApi,
    GetMyMeterApiError,
    GetMyMeterAuthError,
    GetMyMeterMeter,
)
from .const import (
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
    LOGGER,
)
from .identity import stable_entry_unique_id


class GetMyMeterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a GetMyMeter config flow."""

    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize transient flow state."""
        self._pending_credentials: dict[str, str] | None = None
        self._pending_meters: tuple[GetMyMeterMeter, ...] = ()
        self._pending_mode = "user"

    @staticmethod
    def _credentials_schema(
        suggested_username: str | None = None,
    ) -> vol.Schema:
        """Return the username/password setup schema."""
        username_key = vol.Required(CONF_USERNAME)
        if suggested_username:
            username_key = vol.Required(CONF_USERNAME, default=suggested_username)
        return vol.Schema(
            {
                username_key: selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                        autocomplete="username",
                    )
                ),
                vol.Required(CONF_PASSWORD): selector.TextSelector(
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

    async def _async_discover(
        self, credentials: Mapping[str, object]
    ) -> tuple[GetMyMeterMeter, ...]:
        """Validate credentials and discover meters with a private cookie jar."""
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=CookieJar()
        )
        try:
            return await GetMyMeterApi(session, credentials).async_discover_meters()
        finally:
            session.detach()

    @staticmethod
    def _entry_data(
        credentials: Mapping[str, str], meter: GetMyMeterMeter
    ) -> dict[str, str]:
        """Build persistent config data without storing session material."""
        return {
            CONF_USERNAME: credentials[CONF_USERNAME],
            CONF_PASSWORD: credentials[CONF_PASSWORD],
            CONF_COMPANY_ID: meter.company_id,
            CONF_ACCOUNT: meter.account,
            CONF_CHANNEL: meter.channel,
        }

    async def _async_finish(self, meter: GetMyMeterMeter) -> ConfigFlowResult:
        """Create or update the config entry for the selected meter."""
        if self._pending_credentials is None:
            return self.async_abort(reason="unknown")
        data = self._entry_data(self._pending_credentials, meter)
        unique_id = stable_entry_unique_id(data)
        await self.async_set_unique_id(unique_id)

        if self._pending_mode == "reauth":
            entry = self._get_reauth_entry()
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                entry,
                unique_id=unique_id,
                data=data,
            )
        if self._pending_mode == "reconfigure":
            entry = self._get_reconfigure_entry()
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                entry,
                unique_id=unique_id,
                data=data,
            )

        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="GetMyMeter", data=data)

    async def _async_accept_credentials(
        self,
        user_input: Mapping[str, Any],
        *,
        mode: str,
    ) -> ConfigFlowResult | str:
        """Discover meters and continue or finish the flow."""
        credentials = {
            CONF_USERNAME: str(user_input[CONF_USERNAME]),
            CONF_PASSWORD: str(user_input[CONF_PASSWORD]),
        }
        try:
            meters = await self._async_discover(credentials)
        except Exception as err:  # noqa: BLE001
            LOGGER.warning(
                "GetMyMeter credential validation failed: %s: %s",
                type(err).__name__,
                err,
            )
            return self._errors_for_exception(err)

        self._pending_credentials = credentials
        self._pending_meters = meters
        self._pending_mode = mode

        if mode in ("reauth", "reconfigure"):
            entry = (
                self._get_reauth_entry()
                if mode == "reauth"
                else self._get_reconfigure_entry()
            )
            current = (
                str(entry.data.get(CONF_COMPANY_ID, "")),
                str(entry.data.get(CONF_ACCOUNT, "")),
                str(entry.data.get(CONF_CHANNEL, "")),
            )
            for meter in meters:
                if (meter.company_id, meter.account, meter.channel) == current:
                    return await self._async_finish(meter)
            return self.async_abort(reason="wrong_account")

        if len(meters) == 1:
            return await self._async_finish(meters[0])
        return await self.async_step_meter()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle username/password setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._async_accept_credentials(user_input, mode="user")
            if not isinstance(result, str):
                return result
            errors["base"] = result
        return self.async_show_form(
            step_id="user",
            data_schema=self._credentials_schema(),
            errors=errors,
        )

    async def async_step_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select one meter when the portal account exposes several."""
        if not self._pending_meters:
            return self.async_abort(reason="unknown")
        if user_input is not None:
            try:
                meter = self._pending_meters[int(user_input["meter"])]
            except IndexError, KeyError, TypeError, ValueError:
                return self.async_abort(reason="unknown")
            return await self._async_finish(meter)

        options = [
            selector.SelectOptionDict(
                value=str(index),
                label=f"Meter {index + 1} (channel {meter.channel})",
            )
            for index, meter in enumerate(self._pending_meters)
        ]
        return self.async_show_form(
            step_id="meter",
            data_schema=vol.Schema(
                {
                    vol.Required("meter"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_reauth(
        self, _entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle authentication failure or token-only entry migration."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Accept credentials and transparently replace legacy token data."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            result = await self._async_accept_credentials(user_input, mode="reauth")
            if not isinstance(result, str):
                return result
            errors["base"] = result
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._credentials_schema(
                str(entry.data.get(CONF_USERNAME, "")) or None
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change login credentials while preserving the configured meter."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            result = await self._async_accept_credentials(
                user_input, mode="reconfigure"
            )
            if not isinstance(result, str):
                return result
            errors["base"] = result
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._credentials_schema(
                str(entry.data.get(CONF_USERNAME, "")) or None
            ),
            errors=errors,
        )
