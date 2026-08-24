"""Diagnostics redaction tests."""

import json
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant

from custom_components.getmymeter.const import BUCKET_DAILY, BUCKET_MONTHLY, BUCKET_RAW
from custom_components.getmymeter.coordinator import GetMyMeterData
from custom_components.getmymeter.diagnostics import async_get_config_entry_diagnostics
from custom_components.getmymeter.parser import UsageRecord

from .conftest import TEST_CONFIG, make_entry


@pytest.mark.asyncio
async def test_diagnostics_redact_token_and_identity(hass: HomeAssistant) -> None:
    """Diagnostics contain no token, account, company, or channel literals."""
    entry = make_entry()
    entry.add_to_hass(hass)
    records = {
        BUCKET_RAW: (UsageRecord(1704067200000, BUCKET_RAW, 1, 2, None),),
        BUCKET_DAILY: (UsageRecord(1704067200000, BUCKET_DAILY, 3, 4, None),),
        BUCKET_MONTHLY: (UsageRecord(1704067200000, BUCKET_MONTHLY, 5, 6, None),),
    }
    coordinator = SimpleNamespace(
        data=GetMyMeterData(
            raw=records[BUCKET_RAW],
            daily=records[BUCKET_DAILY],
            monthly=records[BUCKET_MONTHLY],
        ),
        history_worker=SimpleNamespace(diagnostics={"status": "complete"}),
        last_update_success=True,
    )
    entry.runtime_data = coordinator
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diagnostics)
    for secret in TEST_CONFIG.values():
        assert secret not in serialized
    assert "identity_hash" not in serialized
    assert "1704067200000" not in serialized
    assert "1" not in diagnostics["coordinator"]["buckets"]["raw"]
    assert diagnostics["api"]["read_only"] is True
