"""Parser coverage for synthetic AMI payloads."""

from datetime import UTC, datetime

import pytest

from custom_components.getmymeter.parser import (
    AmiDataError,
    latest_record,
    parse_ami_data,
)

from .conftest import record_text


@pytest.mark.parametrize("bucket", ["r", "d", "m"])
def test_parse_all_buckets_and_sort(bucket: str) -> None:
    """All supported buckets parse and sort into UTC records."""
    text = " ".join(
        (
            record_text(datetime(2026, 1, 2, 1, tzinfo=UTC), 2, 102),
            record_text(datetime(2026, 1, 2, tzinfo=UTC), 1, 100),
        )
    )
    records = parse_ami_data(text, bucket)
    assert [record.timestamp_ms for record in records] == sorted(
        record.timestamp_ms for record in records
    )
    assert records[0].bucket == bucket
    assert records[0].timestamp_utc == "2026-01-02T00:00:00+00:00"
    assert latest_record(records) == records[-1]


def test_parser_skips_malformed_and_nonfinite_rows() -> None:
    """Malformed rows do not become recorder data."""
    text = " ".join(
        (
            "not-a-row",
            "1|bad|2|0|",
            "999999999999999999999999999|1|2|0|",
            "1704067200000|1|2|0|",
            "1704067201000|nan|2|0|",
        )
    )
    records = parse_ami_data(text, "d")
    assert len(records) == 1
    assert records[0].usage_gallons == 1


def test_parser_rejects_empty_payload() -> None:
    """An empty or wholly malformed response is not usable history."""
    with pytest.raises(AmiDataError):
        parse_ami_data("bad|payload", "d")


def test_parser_rejects_unknown_bucket() -> None:
    """Unknown request buckets fail closed."""
    with pytest.raises(ValueError):
        parse_ami_data("1704067200000|1|2|0|", "x")
