"""Coordinator recovery and primary-data tests."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.getmymeter.api import GetMyMeterApiError, GetMyMeterAuthError
from custom_components.getmymeter.const import BUCKET_DAILY, BUCKET_MONTHLY, BUCKET_RAW
from custom_components.getmymeter.coordinator import GetMyMeterCoordinator
from custom_components.getmymeter.parser import UsageRecord

from .conftest import make_entry

RECORDS = {
    BUCKET_RAW: (UsageRecord(1704067200000, BUCKET_RAW, 1, 10, None),),
    BUCKET_DAILY: (UsageRecord(1704067200000, BUCKET_DAILY, 2, 10, None),),
    BUCKET_MONTHLY: (UsageRecord(1704067200000, BUCKET_MONTHLY, 3, 10, None),),
}


@pytest.mark.asyncio
async def test_optional_history_failure_does_not_break_daily(
    hass: HomeAssistant,
) -> None:
    """Raw/monthly failures are isolated and retried on the next refresh."""
    entry = make_entry()
    entry.add_to_hass(hass)
    api = AsyncMock()
    api.async_fetch_bucket.side_effect = [
        RECORDS[BUCKET_DAILY],
        GetMyMeterApiError("raw unavailable"),
        RECORDS[BUCKET_MONTHLY],
    ]
    coordinator = GetMyMeterCoordinator(hass, entry, api)
    data = await coordinator._async_update_data()
    assert data.daily == RECORDS[BUCKET_DAILY]
    assert data.monthly == RECORDS[BUCKET_MONTHLY]
    assert data.raw == ()
    assert data.history_failures == (BUCKET_RAW,)

    api.async_fetch_bucket.side_effect = [
        RECORDS[BUCKET_DAILY],
        RECORDS[BUCKET_RAW],
        RECORDS[BUCKET_MONTHLY],
    ]
    recovered = await coordinator._async_update_data()
    assert recovered.history_failures == ()
    assert recovered.raw == RECORDS[BUCKET_RAW]
    assert [call.args[0] for call in api.async_fetch_bucket.call_args_list] == [
        BUCKET_DAILY,
        BUCKET_RAW,
        BUCKET_MONTHLY,
        BUCKET_DAILY,
        BUCKET_RAW,
        BUCKET_MONTHLY,
    ]


@pytest.mark.asyncio
async def test_daily_failure_is_primary_update_failure(hass: HomeAssistant) -> None:
    """A daily failure makes the live coordinator unavailable."""
    entry = make_entry()
    entry.add_to_hass(hass)
    api = AsyncMock()
    api.async_fetch_bucket.side_effect = GetMyMeterApiError("daily unavailable")
    coordinator = GetMyMeterCoordinator(hass, entry, api)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    api.async_fetch_bucket.assert_awaited_once_with(BUCKET_DAILY)


@pytest.mark.asyncio
async def test_authentication_failure_requests_reauth(hass: HomeAssistant) -> None:
    """Authentication failures are not downgraded to ordinary update errors."""
    entry = make_entry()
    entry.add_to_hass(hass)
    api = AsyncMock()
    api.async_fetch_bucket.side_effect = GetMyMeterAuthError("token rejected")
    coordinator = GetMyMeterCoordinator(hass, entry, api)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
