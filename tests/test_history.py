"""Deterministic history-boundary and statistics-builder tests."""

from datetime import UTC, datetime

import pytest

from custom_components.getmymeter.const import (
    BUCKET_DAILY,
    BUCKET_MONTHLY,
    BUCKET_RAW,
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    DOMAIN,
)
from custom_components.getmymeter.history import (
    build_all_history_statistics,
    build_bucket_statistics,
    canonical_start,
    statistic_metadata,
)
from custom_components.getmymeter.identity import statistic_id
from custom_components.getmymeter.parser import UsageRecord

from .conftest import NOW, TEST_CONFIG


def make_record(
    value: datetime,
    bucket: str,
    usage: float,
    cumulative: float | None,
) -> UsageRecord:
    """Create one synthetic usage record."""
    return UsageRecord(
        timestamp_ms=int(value.timestamp() * 1000),
        bucket=bucket,
        usage_gallons=usage,
        cumulative_gallons=cumulative,
        aux_value=None,
    )


def test_raw_boundary_and_incomplete_hour() -> None:
    """Raw rows use UTC top-of-hour starts and exclude the current hour."""
    boundary = make_record(
        datetime(2026, 1, 2, 11, 59, 59, tzinfo=UTC), BUCKET_RAW, 7, 107
    )
    ordinary = make_record(datetime(2026, 1, 2, 11, 12, tzinfo=UTC), BUCKET_RAW, 3, 100)
    incomplete = make_record(
        datetime(2026, 8, 24, 12, 5, tzinfo=UTC), BUCKET_RAW, 9, 200
    )
    assert canonical_start(boundary, BUCKET_RAW) == datetime(2026, 1, 2, 12, tzinfo=UTC)
    result = build_bucket_statistics(
        [boundary, ordinary, incomplete], BUCKET_RAW, now=NOW
    )
    assert [row["start"] for row in result.statistics] == [
        datetime(2026, 1, 2, 11, tzinfo=UTC),
        datetime(2026, 1, 2, 12, tzinfo=UTC),
    ]
    assert result.incomplete_count == 1


def test_daily_and_monthly_period_starts_and_incomplete_policy() -> None:
    """Daily and monthly records use period starts and skip open periods."""
    daily_complete = make_record(
        datetime(2026, 8, 23, 23, 59, 59, tzinfo=UTC), BUCKET_DAILY, 10, 110
    )
    daily_open = make_record(
        datetime(2026, 8, 24, 10, tzinfo=UTC), BUCKET_DAILY, 11, 121
    )
    monthly_complete = make_record(
        datetime(2026, 7, 31, 23, 59, 59, tzinfo=UTC), BUCKET_MONTHLY, 30, 300
    )
    monthly_open = make_record(
        datetime(2026, 8, 10, tzinfo=UTC), BUCKET_MONTHLY, 31, 331
    )
    daily = build_bucket_statistics([daily_open, daily_complete], BUCKET_DAILY, now=NOW)
    monthly = build_bucket_statistics(
        [monthly_open, monthly_complete], BUCKET_MONTHLY, now=NOW
    )
    assert daily.statistics[0]["start"] == datetime(2026, 8, 23, tzinfo=UTC)
    assert monthly.statistics[0]["start"] == datetime(2026, 7, 1, tzinfo=UTC)
    assert daily.incomplete_count == 1
    assert monthly.incomplete_count == 1


def test_same_hour_latest_source_wins_and_corrections_are_preserved() -> None:
    """A later source row replaces a canonical row without adding usage."""
    first = make_record(datetime(2026, 1, 2, 1, 5, tzinfo=UTC), BUCKET_RAW, 2, 102)
    correction = make_record(
        datetime(2026, 1, 2, 1, 55, tzinfo=UTC), BUCKET_RAW, 5, 105
    )
    result = build_bucket_statistics([correction, first], BUCKET_RAW, now=NOW)
    assert len(result.statistics) == 1
    assert result.statistics[0]["state"] == 5
    assert result.statistics[0]["sum"] == 105
    assert result.collision_count == 1


def test_missing_sum_reconstructs_and_decrease_is_not_clamped() -> None:
    """Missing cumulative readings are explicit fallback rows and decreases survive."""
    records = [
        make_record(
            datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC), BUCKET_DAILY, 2, None
        ),
        make_record(datetime(2026, 1, 2, 23, 59, 59, tzinfo=UTC), BUCKET_DAILY, 3, 4),
        make_record(datetime(2026, 1, 3, 23, 59, 59, tzinfo=UTC), BUCKET_DAILY, 1, 3),
    ]
    result = build_bucket_statistics(records, BUCKET_DAILY, now=NOW)
    assert [row["sum"] for row in result.statistics] == [2, 4, 3]
    assert result.reconstructed_sum_count == 1
    assert result.decrease_count == 1


def test_three_series_have_separate_stable_metadata() -> None:
    """Raw, daily, and monthly metadata never share an overlapping ID."""
    records = {
        bucket: [
            make_record(datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC), bucket, 1, 1)
        ]
        for bucket in (BUCKET_RAW, BUCKET_DAILY, BUCKET_MONTHLY)
    }
    built = build_all_history_statistics(records, now=NOW)
    metadata = [statistic_metadata(TEST_CONFIG, bucket) for bucket in records]
    ids = [item["statistic_id"] for item in metadata]
    assert len(set(ids)) == 3
    assert all(item["source"] == DOMAIN for item in metadata)
    assert all(item["has_sum"] is True for item in metadata)
    assert all(item["mean_type"].name == "NONE" for item in metadata)
    assert all(item["unit_of_measurement"] == "gal" for item in metadata)
    assert all(item["unit_class"] == "volume" for item in metadata)
    assert set(built) == {BUCKET_RAW, BUCKET_DAILY, BUCKET_MONTHLY}
    assert all(built[bucket].statistics for bucket in built)
    assert all(
        TEST_CONFIG[CONF_ACCOUNT] not in statistic_id(TEST_CONFIG, bucket)
        and TEST_CONFIG[CONF_COMPANY_ID] not in statistic_id(TEST_CONFIG, bucket)
        and TEST_CONFIG[CONF_CHANNEL] not in statistic_id(TEST_CONFIG, bucket)
        for bucket in records
    )


def test_invalid_bucket_is_rejected() -> None:
    """The pure builder does not accept a combined or unknown series."""
    with pytest.raises(ValueError):
        build_bucket_statistics([], "combined", now=NOW)
