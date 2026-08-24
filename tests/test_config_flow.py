"""Config-flow, reauth, and reconfigure tests."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant

from custom_components.getmymeter.api import (
    GetMyMeterAuthError,
    GetMyMeterConnectionError,
)
from custom_components.getmymeter.config_flow import GetMyMeterConfigFlow
from custom_components.getmymeter.const import (
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    CONF_TOKEN,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
)
from custom_components.getmymeter.identity import stable_entry_unique_id

from .conftest import TEST_CONFIG, make_entry


@pytest.mark.asyncio
async def test_user_flow_creates_stable_hashed_entry(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Successful setup stores values and never uses an entry UUID as identity."""
    with (
        patch.object(GetMyMeterConfigFlow, "_async_validate", new=AsyncMock()),
        patch(
            "custom_components.getmymeter.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.getmymeter.async_unload_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=TEST_CONFIG
        )
        await hass.config_entries.async_remove(result["result"].entry_id)
    assert result["type"] == "create_entry"
    assert result["data"] == TEST_CONFIG
    assert result["result"].unique_id == stable_entry_unique_id(TEST_CONFIG)
    assert result["result"].unique_id != result["result"].entry_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (GetMyMeterAuthError("bad token"), ERROR_INVALID_AUTH),
        (GetMyMeterConnectionError("offline"), ERROR_CANNOT_CONNECT),
        (RuntimeError("unexpected"), ERROR_UNKNOWN),
    ],
)
async def test_user_flow_classifies_validation_failures(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    failure: Exception,
    expected: str,
) -> None:
    """Invalid authentication and connectivity errors are translated safely."""
    with patch.object(
        GetMyMeterConfigFlow, "_async_validate", new=AsyncMock(side_effect=failure)
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=TEST_CONFIG
        )
    assert result["errors"]["base"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (GetMyMeterAuthError("replacement rejected"), ERROR_INVALID_AUTH),
        (GetMyMeterConnectionError("replacement offline"), ERROR_CANNOT_CONNECT),
    ],
)
async def test_reauth_classifies_replacement_failures(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    failure: Exception,
    expected: str,
) -> None:
    """Reauth keeps the entry unchanged when replacement validation fails."""
    entry = make_entry()
    entry.add_to_hass(hass)
    with patch.object(
        GetMyMeterConfigFlow, "_async_validate", new=AsyncMock(side_effect=failure)
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_TOKEN: "replacement-synthetic-token"}
        )
    assert result["type"] == "form"
    assert result["errors"]["base"] == expected
    assert entry.data[CONF_TOKEN] == TEST_CONFIG[CONF_TOKEN]


@pytest.mark.asyncio
async def test_reauth_updates_only_token(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Reauth validates a replacement and preserves the other entry fields."""
    entry = make_entry()
    entry.add_to_hass(hass)
    replacement = "replacement-synthetic-token"
    with (
        patch.object(GetMyMeterConfigFlow, "_async_validate", new=AsyncMock()),
        patch.object(
            hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_TOKEN: replacement}
        )
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == replacement
    assert entry.data[CONF_ACCOUNT] == TEST_CONFIG[CONF_ACCOUNT]
    assert entry.data[CONF_COMPANY_ID] == TEST_CONFIG[CONF_COMPANY_ID]
    assert entry.data[CONF_CHANNEL] == TEST_CONFIG[CONF_CHANNEL]


@pytest.mark.asyncio
async def test_reconfigure_changes_identity(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Reconfigure validates a new identity and gets a new stable hash."""
    entry = make_entry()
    entry.add_to_hass(hass)
    new_data = {
        **TEST_CONFIG,
        CONF_COMPANY_ID: "synthetic-company-2",
        CONF_ACCOUNT: "synthetic-account-2",
        CONF_CHANNEL: "synthetic-channel-2",
    }
    with (
        patch.object(GetMyMeterConfigFlow, "_async_validate", new=AsyncMock()),
        patch.object(
            hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        assert result["type"] == "form", result
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=new_data
        )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == new_data
    assert entry.unique_id == stable_entry_unique_id(new_data)
