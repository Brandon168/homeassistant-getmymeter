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

NEW_RECORDS = {
    BUCKET_RAW: (
        UsageRecord(
            int(datetime(2026, 1, 2, 23, 59, 59, tzinfo=UTC).timestamp() * 1000),
            BUCKET_RAW,
            2,
            20,
            None,
        ),
    ),
    BUCKET_DAILY: (
        UsageRecord(
            int(datetime(2026, 1, 2, 23, 59, 59, tzinfo=UTC).timestamp() * 1000),
            BUCKET_DAILY,
            2,
            20,
            None,
        ),
    ),
    BUCKET_MONTHLY: (
        UsageRecord(
            int(datetime(2026, 2, 1, 23, 59, 59, tzinfo=UTC).timestamp() * 1000),
            BUCKET_MONTHLY,
            2,
            20,
            None,
        ),
    ),
}


@pytest.mark.asyncio
async def test_worker_full_replay_queues_three_metadata_series(
    hass: HomeAssistant,
) -> None:
    """The first run is a full replay that queues all three series."""
    entry = make_entry()
    api = AsyncMock()
    api.async_fetch_bucket.side_effect = [
        RECORDS[BUCKET_RAW],
        RECORDS[BUCKET_DAILY],
        RECORDS[BUCKET_MONTHLY],
    ]
    worker = GetMyMeterHistoryWorker(hass, entry, api)
    with patch(
        "custom_components.getmymeter.history.async_add_external_statistics"
    ) as add_statistics:
        await worker.async_run()

    calls = add_statistics.call_args_list
    assert add_statistics.call_count == 3
    assert {call.args[1]["statistic_id"] for call in calls} == {
        statistic_id(entry.data, BUCKET_RAW),
        statistic_id(entry.data, BUCKET_DAILY),
        statistic_id(entry.data, BUCKET_MONTHLY),
    }
    assert all(call.args[1]["source"] == "getmymeter" for call in calls)
    assert all(call.args[1]["mean_type"].name == "NONE" for call in calls)
    assert all(call.args[1]["has_sum"] is True for call in calls)
    assert all(call.args[1]["unit_class"] == "volume" for call in calls)
    assert all(call.args[1]["unit_of_measurement"] == "gal" for call in calls)
    assert all(call.args[2][0]["state"] == 1 for call in calls)
    assert all(call.args[2][0]["sum"] == 10 for call in calls)
    assert worker.diagnostics["status"] == "complete"
    assert worker.diagnostics["mode"] == "full"


@pytest.mark.asyncio
async def test_worker_incremental_run_imports_only_new_rows(
    hass: HomeAssistant,
) -> None:
    """After a full replay, an incremental run queues only newer rows."""
    entry = make_entry()
    api = AsyncMock()
    api.async_fetch_bucket.side_effect = [
        RECORDS[BUCKET_RAW],
        RECORDS[BUCKET_DAILY],
        RECORDS[BUCKET_MONTHLY],
        RECORDS[BUCKET_RAW] + NEW_RECORDS[BUCKET_RAW],
        RECORDS[BUCKET_DAILY] + NEW_RECORDS[BUCKET_DAILY],
        RECORDS[BUCKET_MONTHLY] + NEW_RECORDS[BUCKET_MONTHLY],
    ]
    worker = GetMyMeterHistoryWorker(hass, entry, api)
    with patch(
        "custom_components.getmymeter.history.async_add_external_statistics"
    ) as add_statistics:
        await worker.async_run()
        await worker.async_run()

    incremental_calls = add_statistics.call_args_list[3:]
    assert add_statistics.call_count == 6
    assert all(len(call.args[2]) == 1 for call in incremental_calls)
    assert all(call.args[2][0]["state"] == 2 for call in incremental_calls)
    assert all(call.args[2][0]["sum"] == 20 for call in incremental_calls)
    assert worker.diagnostics["mode"] == "incremental"


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
