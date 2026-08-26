"""Pure parsers for the GetMyMeter AMI response format."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from decimal import Decimal, InvalidOperation

BUCKETS = {"r": "raw/hourly", "d": "daily", "m": "monthly"}


class AmiDataError(ValueError):
    """Raised when an AMI response contains no usable records."""


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One AMI usage sample."""

    timestamp_ms: int
    bucket: str
    usage_gallons: float
    cumulative_gallons: float | None
    aux_value: float | None

    @property
    def timestamp_datetime(self) -> datetime:
        """Return the sample timestamp as an aware UTC datetime."""
        return datetime.fromtimestamp(self.timestamp_ms / 1000, UTC)

    @property
    def timestamp_utc(self) -> str:
        """Return the portal's encoded wall-clock timestamp for diagnostics."""
        return self.timestamp_datetime.isoformat()

    def timestamp_in(self, source_timezone: tzinfo) -> datetime:
        """Interpret the portal epoch fields as wall-clock time in its timezone."""
        wall_clock = self.timestamp_datetime.replace(tzinfo=None)
        return wall_clock.replace(tzinfo=source_timezone).astimezone(UTC)


def _parse_number(value: str) -> float | None:
    """Parse a portal number while preserving empty optional fields."""
    value = value.strip()
    if not value:
        return None
    try:
        parsed = float(Decimal(value))
    except InvalidOperation, ValueError, OverflowError:
        return None
    return parsed if math.isfinite(parsed) else None


def _valid_timestamp(timestamp_ms: int) -> bool:
    """Return whether an epoch-millisecond value can be represented safely."""
    try:
        datetime.fromtimestamp(timestamp_ms / 1000, UTC)
    except OverflowError, OSError, ValueError:
        return False
    return True


def parse_ami_data(text: str, bucket: str) -> tuple[UsageRecord, ...]:
    """Parse whitespace-separated ``epoch|usage|cumulative|aux|`` rows."""
    if bucket not in BUCKETS:
        raise ValueError(f"bucket must be one of {sorted(BUCKETS)}")

    records: list[UsageRecord] = []
    for token in text.split():
        parts = token.split("|")
        if len(parts) < 4:
            continue
        try:
            timestamp_ms = int(parts[0].strip())
        except ValueError:
            continue
        if not _valid_timestamp(timestamp_ms):
            continue
        usage = _parse_number(parts[1])
        if usage is None:
            continue
        records.append(
            UsageRecord(
                timestamp_ms=timestamp_ms,
                bucket=bucket,
                usage_gallons=usage,
                cumulative_gallons=_parse_number(parts[2]),
                aux_value=_parse_number(parts[3]),
            )
        )

    if not records:
        raise AmiDataError("The portal returned no usable AMI records")
    return tuple(sorted(records, key=lambda record: record.timestamp_ms))


def latest_record(records: tuple[UsageRecord, ...]) -> UsageRecord | None:
    """Return the newest record, or ``None`` for an empty sequence."""
    return max(records, key=lambda record: record.timestamp_ms, default=None)
