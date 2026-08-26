"""Config-flow, meter-selection, reauth, and reconfigure tests."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant

from custom_components.getmymeter import async_migrate_entry
from custom_components.getmymeter.api import (
    GetMyMeterAuthError,
    GetMyMeterConnectionError,
    GetMyMeterMeter,
)
from custom_components.getmymeter.config_flow import GetMyMeterConfigFlow
from custom_components.getmymeter.const import (
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
)
from custom_components.getmymeter.identity import stable_entry_unique_id

from .conftest import LEGACY_TEST_CONFIG, TEST_CONFIG, make_entry

METER = GetMyMeterMeter("138", "synthetic-account", "1")
CREDENTIALS = {
    CONF_USERNAME: TEST_CONFIG[CONF_USERNAME],
    CONF_PASSWORD: TEST_CONFIG[CONF_PASSWORD],
}
EXPECTED_DATA = {
    **CREDENTIALS,
    CONF_COMPANY_ID: METER.company_id,
    CONF_ACCOUNT: METER.account,
    CONF_CHANNEL: METER.channel,
}


@pytest.mark.asyncio
async def test_legacy_entry_migration_preserves_token_until_reauth(
    hass: HomeAssistant,
) -> None:
    """Schema migration cannot discard the only working legacy credential."""
    entry = make_entry(**LEGACY_TEST_CONFIG)
    entry.add_to_hass(hass)
    original = dict(entry.data)
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.minor_version == 1
    assert entry.data == original


@pytest.mark.asyncio
async def test_user_flow_needs_only_credentials_and_creates_stable_entry(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Username/password setup discovers identity and stores no session token."""
    with (
        patch.object(
            GetMyMeterConfigFlow,
            "_async_discover",
            new=AsyncMock(return_value=(METER,)),
        ),
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
        assert [field.schema for field in result["data_schema"].schema] == [
            CONF_USERNAME,
            CONF_PASSWORD,
        ]
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=CREDENTIALS
        )
        await hass.config_entries.async_remove(result["result"].entry_id)

    assert result["type"] == "create_entry"
    assert result["data"] == EXPECTED_DATA
    assert CONF_TOKEN not in result["data"]
    assert result["result"].unique_id == stable_entry_unique_id(EXPECTED_DATA)


@pytest.mark.asyncio
async def test_multiple_meters_adds_selection_step(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Only genuinely multi-meter accounts require a second setup step."""
    meters = (METER, GetMyMeterMeter("138", "synthetic-account-2", "2"))
    with (
        patch.object(
            GetMyMeterConfigFlow,
            "_async_discover",
            new=AsyncMock(return_value=meters),
        ),
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
            result["flow_id"], user_input=CREDENTIALS
        )
        assert result["type"] == "form"
        assert result["step_id"] == "meter"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"meter": "1"}
        )
        await hass.config_entries.async_remove(result["result"].entry_id)

    assert result["data"][CONF_ACCOUNT] == "synthetic-account-2"
    assert result["data"][CONF_CHANNEL] == "2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (GetMyMeterAuthError("bad credentials"), ERROR_INVALID_AUTH),
        (GetMyMeterConnectionError("offline"), ERROR_CANNOT_CONNECT),
        (RuntimeError("unexpected"), ERROR_UNKNOWN),
    ],
)
async def test_user_flow_classifies_discovery_failures(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    failure: Exception,
    expected: str,
) -> None:
    """Credential and connectivity failures are translated safely."""
    with patch.object(
        GetMyMeterConfigFlow,
        "_async_discover",
        new=AsyncMock(side_effect=failure),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=CREDENTIALS
        )
    assert result["errors"]["base"] == expected


@pytest.mark.asyncio
async def test_reauth_migrates_legacy_token_entry_to_credentials(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """The one-time reauth removes the stored token after discovery succeeds."""
    entry = make_entry(**LEGACY_TEST_CONFIG)
    entry.add_to_hass(hass)
    with (
        patch.object(
            GetMyMeterConfigFlow,
            "_async_discover",
            new=AsyncMock(return_value=(METER,)),
        ),
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
            result["flow_id"], user_input=CREDENTIALS
        )

    assert result["reason"] == "reauth_successful"
    assert entry.data == EXPECTED_DATA
    assert CONF_TOKEN not in entry.data


@pytest.mark.asyncio
async def test_reauth_failure_keeps_legacy_entry_unchanged(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Rejected credentials cannot destroy the existing token-only entry."""
    entry = make_entry(**LEGACY_TEST_CONFIG)
    entry.add_to_hass(hass)
    original = dict(entry.data)
    with patch.object(
        GetMyMeterConfigFlow,
        "_async_discover",
        new=AsyncMock(side_effect=GetMyMeterAuthError("rejected")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=CREDENTIALS
        )
    assert result["type"] == "form"
    assert result["errors"]["base"] == ERROR_INVALID_AUTH
    assert entry.data == original


@pytest.mark.asyncio
async def test_reauth_refuses_credentials_for_a_different_meter(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Reauth cannot silently repoint an entry to an unrelated meter."""
    entry = make_entry()
    entry.add_to_hass(hass)
    other = GetMyMeterMeter("138", "different-account", "2")
    original = dict(entry.data)
    with patch.object(
        GetMyMeterConfigFlow,
        "_async_discover",
        new=AsyncMock(return_value=(other,)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=CREDENTIALS
        )
    assert result["type"] == "abort"
    assert result["reason"] == "wrong_account"
    assert entry.data == original


@pytest.mark.asyncio
async def test_reconfigure_updates_password_and_preserves_discovered_identity(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Reconfigure validates replacement credentials against the same meter."""
    entry = make_entry(**{**EXPECTED_DATA, CONF_PASSWORD: "old-synthetic-password"})
    entry.add_to_hass(hass)
    with (
        patch.object(
            GetMyMeterConfigFlow,
            "_async_discover",
            new=AsyncMock(return_value=(METER,)),
        ),
        patch.object(
            hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=CREDENTIALS
        )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == EXPECTED_DATA
