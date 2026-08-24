"""External-statistics queueing and replay tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.getmymeter.api import GetMyMeterApiError
from custom_components.getmymeter.const import BUCKET_DAILY, BUCKET_MONTHLY, BUCKET_RAW
from custom_components.getmymeter.history import GetMyMeterHistoryWorker
from custom_components.getmymeter.identity import statistic_id
from custom_components.getmymeter.parser import UsageRecord

from .conftest import make_entry

RECORDS = {
    bucket: (
        UsageRecord(
            int(datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC).timestamp() * 1000),
            bucket,
            1,
            10,
            None,
        ),
    )
    for bucket in (BUCKET_RAW, BUCKET_DAILY, BUCKET_MONTHLY)
}


@pytest.mark.asyncio
async def test_worker_queues_three_metadata_series_and_replays_idempotently(
    hass: HomeAssistant,
) -> None:
    """Every complete bucket is queued with its own stable metadata and rows."""
    entry = make_entry()
    api = AsyncMock()
    api.async_fetch_bucket.side_effect = [
        RECORDS[BUCKET_RAW],
        RECORDS[BUCKET_DAILY],
        RECORDS[BUCKET_MONTHLY],
        RECORDS[BUCKET_RAW],
        RECORDS[BUCKET_DAILY],
        RECORDS[BUCKET_MONTHLY],
    ]
    worker = GetMyMeterHistoryWorker(hass, entry, api)
    with patch(
        "custom_components.getmymeter.history.async_add_external_statistics"
    ) as add_statistics:
        await worker.async_run()
        await worker.async_run()

    assert add_statistics.call_count == 6
    first_run = add_statistics.call_args_list[:3]
    assert {call.args[1]["statistic_id"] for call in first_run} == {
        statistic_id(entry.data, BUCKET_RAW),
        statistic_id(entry.data, BUCKET_DAILY),
        statistic_id(entry.data, BUCKET_MONTHLY),
    }
    assert all(call.args[1]["source"] == "getmymeter" for call in first_run)
    assert all(call.args[1]["mean_type"].name == "NONE" for call in first_run)
    assert all(call.args[1]["has_sum"] is True for call in first_run)
    assert all(call.args[1]["unit_class"] == "volume" for call in first_run)
    assert all(call.args[1]["unit_of_measurement"] == "gal" for call in first_run)
    assert all(call.args[2][0]["state"] == 1 for call in first_run)
    assert all(call.args[2][0]["sum"] == 10 for call in first_run)
    assert worker.diagnostics["status"] == "complete"


@pytest.mark.asyncio
async def test_worker_isolates_one_bucket_failure(hass: HomeAssistant) -> None:
    """A history bucket failure does not discard successfully queued buckets."""
    entry = make_entry()
    api = AsyncMock()
    api.async_fetch_bucket.side_effect = [
        GetMyMeterApiError("raw failure"),
        RECORDS[BUCKET_DAILY],
        RECORDS[BUCKET_MONTHLY],
    ]
    worker = GetMyMeterHistoryWorker(hass, entry, api)
    with patch(
        "custom_components.getmymeter.history.async_add_external_statistics"
    ) as add_statistics:
        await worker.async_run()
    assert add_statistics.call_count == 2
    assert worker.diagnostics["status"] == "partial"
    assert worker.diagnostics["buckets"][BUCKET_RAW]["status"] == "fetch_failed"
    assert worker.diagnostics["buckets"][BUCKET_DAILY]["status"] == "import_queued"
