"""Home Assistant 2026.8.3 Recorder integration tests."""

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any

import pytest
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant

from custom_components.getmymeter.const import BUCKET_DAILY, BUCKET_MONTHLY, BUCKET_RAW
from custom_components.getmymeter.history import (
    build_bucket_statistics,
    statistic_metadata,
)
from custom_components.getmymeter.parser import UsageRecord

from .conftest import NOW, make_entry


@pytest.mark.asyncio
async def test_external_statistics_metadata_rows_idempotence_and_correction(
    async_test_recorder: Callable[..., Any], hass: HomeAssistant
) -> None:
    """Recorder stores three external series, updates corrections, and dedupes."""
    entry = make_entry()
    records = {
        BUCKET_RAW: (
            UsageRecord(
                int(datetime(2026, 1, 1, 1, 5, tzinfo=UTC).timestamp() * 1000),
                BUCKET_RAW,
                1,
                101,
                None,
            ),
        ),
        BUCKET_DAILY: (
            UsageRecord(
                int(datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC).timestamp() * 1000),
                BUCKET_DAILY,
                2,
                102,
                None,
            ),
        ),
        BUCKET_MONTHLY: (
            UsageRecord(
                int(datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC).timestamp() * 1000),
                BUCKET_MONTHLY,
                3,
                103,
                None,
            ),
        ),
    }
    prepared = {
        bucket: build_bucket_statistics(values, bucket, now=NOW)
        for bucket, values in records.items()
    }
    statistic_ids = {
        statistic_metadata(entry.data, bucket)["statistic_id"] for bucket in records
    }

    async with async_test_recorder(hass) as recorder:
        for bucket in records:
            async_add_external_statistics(
                hass,
                statistic_metadata(entry.data, bucket),
                prepared[bucket].statistics,
            )
        await hass.async_block_till_done()
        await recorder.async_block_till_done()

        metadata = await hass.async_add_executor_job(
            partial(get_metadata, hass, statistic_ids=statistic_ids)
        )
        assert set(metadata) == statistic_ids
        assert all(item[1]["source"] == "getmymeter" for item in metadata.values())
        assert all(item[1]["mean_type"].name == "NONE" for item in metadata.values())
        assert all(item[1]["has_sum"] is True for item in metadata.values())
        assert all(item[1]["unit_class"] == "volume" for item in metadata.values())
        assert all(
            item[1]["unit_of_measurement"] == "gal" for item in metadata.values()
        )

        for bucket in records:
            async_add_external_statistics(
                hass,
                statistic_metadata(entry.data, bucket),
                prepared[bucket].statistics,
            )
        await hass.async_block_till_done()
        await recorder.async_block_till_done()

        correction_record = UsageRecord(
            int(datetime(2026, 1, 1, 1, 55, tzinfo=UTC).timestamp() * 1000),
            BUCKET_RAW,
            9,
            109,
            None,
        )
        correction = build_bucket_statistics(
            [records[BUCKET_RAW][0], correction_record], BUCKET_RAW, now=NOW
        )
        async_add_external_statistics(
            hass,
            statistic_metadata(entry.data, BUCKET_RAW),
            correction.statistics,
        )
        await hass.async_block_till_done()
        await recorder.async_block_till_done()

        rows = await hass.async_add_executor_job(
            partial(
                statistics_during_period,
                hass,
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 3, tzinfo=UTC),
                statistic_ids,
                "hour",
                None,
                {"state", "sum"},
            )
        )

    assert set(rows) == statistic_ids
    assert all(len(bucket_rows) == 1 for bucket_rows in rows.values())
    raw_rows = rows[statistic_metadata(entry.data, BUCKET_RAW)["statistic_id"]]
    assert raw_rows[0]["state"] == 9
    assert raw_rows[0]["sum"] == 109
    assert raw_rows[0]["start"] == datetime(2026, 1, 1, 1, tzinfo=UTC).timestamp()
