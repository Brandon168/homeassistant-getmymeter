"""Deterministic external-statistics replay for GetMyMeter."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from homeassistant.components.recorder.models.statistics import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_conversion import VolumeConverter

from .api import GetMyMeterApi, GetMyMeterApiError, GetMyMeterAuthError
from .const import (
    BUCKET_DAILY,
    BUCKET_MONTHLY,
    BUCKET_RAW,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HISTORY_BUCKETS,
    HISTORY_SCHEMA_VERSION,
    LOGGER,
)
from .identity import statistic_id
from .parser import UsageRecord


@dataclass(frozen=True, slots=True)
class HistoryBuildResult:
    """Prepared rows and deterministic data-quality counters for one bucket."""

    bucket: str
    statistics: tuple[StatisticData, ...]
    collision_count: int
    incomplete_count: int
    reconstructed_sum_count: int
    decrease_count: int
    invalid_count: int


def _as_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("History timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _source_datetime(record: UsageRecord) -> datetime:
    """Return a source record timestamp in UTC."""
    return record.timestamp_datetime


def canonical_start(record: UsageRecord, bucket: str | None = None) -> datetime:
    """Map a portal record to a deterministic UTC top-of-hour start.

    Raw boundary markers at ``xx:59:59`` are treated as the end of that hour,
    then moved to the following hour before flooring. Daily and monthly rows
    represent their UTC calendar period and therefore use the period start.
    """
    bucket = bucket or record.bucket
    source = _source_datetime(record)
    if bucket == BUCKET_RAW:
        if source.minute == 59 and source.second == 59 and source.microsecond == 0:
            source += timedelta(seconds=1)
        return source.replace(minute=0, second=0, microsecond=0)
    if bucket == BUCKET_DAILY:
        return source.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == BUCKET_MONTHLY:
        return source.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"Unsupported GetMyMeter history bucket: {bucket}")


def _next_month(start: datetime) -> datetime:
    """Return the first UTC instant of the next calendar month."""
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def _period_end(start: datetime, bucket: str) -> datetime:
    """Return the end boundary for a canonical source period."""
    if bucket == BUCKET_RAW:
        return start + timedelta(hours=1)
    if bucket == BUCKET_DAILY:
        return start + timedelta(days=1)
    if bucket == BUCKET_MONTHLY:
        return _next_month(start)
    raise ValueError(f"Unsupported GetMyMeter history bucket: {bucket}")


def _is_complete(
    record: UsageRecord, start: datetime, bucket: str, now: datetime
) -> bool:
    """Apply the explicit incomplete-period publication policy."""
    source = _source_datetime(record)
    if bucket == BUCKET_RAW and source.minute == 59 and source.second == 59:
        return source <= now
    return _period_end(start, bucket) <= now


def build_bucket_statistics(
    records: tuple[UsageRecord, ...] | list[UsageRecord],
    bucket: str,
    *,
    now: datetime | None = None,
) -> HistoryBuildResult:
    """Build one bucket without network or recorder side effects.

    Rows are sorted by canonical start. If several source records map to the
    same start, the latest source timestamp wins; an equal timestamp uses the
    last input row. Missing cumulative values use a deterministic reconstructed
    running sum and are counted for diagnostics. Source cumulative decreases
    are preserved rather than clamped.
    """
    if bucket not in HISTORY_BUCKETS:
        raise ValueError(f"Unsupported GetMyMeter history bucket: {bucket}")
    now_utc = _as_utc(now or datetime.now(UTC))

    candidates: list[tuple[datetime, UsageRecord, int]] = []
    invalid_count = 0
    for index, record in enumerate(records):
        if record.bucket != bucket or not math.isfinite(record.usage_gallons):
            invalid_count += 1
            continue
        if record.cumulative_gallons is not None and not math.isfinite(
            record.cumulative_gallons
        ):
            invalid_count += 1
            continue
        try:
            start = canonical_start(record, bucket)
        except OverflowError, OSError, ValueError:
            invalid_count += 1
            continue
        candidates.append((start, record, index))

    candidates.sort(key=lambda item: (item[0], item[1].timestamp_ms, item[2]))
    winners: list[tuple[datetime, UsageRecord]] = []
    collision_count = 0
    position = 0
    while position < len(candidates):
        start = candidates[position][0]
        end = position + 1
        while end < len(candidates) and candidates[end][0] == start:
            end += 1
        collision_count += end - position - 1
        _winner_start, winner, _winner_index = candidates[end - 1]
        winners.append((start, winner))
        position = end

    statistics: list[StatisticData] = []
    incomplete_count = 0
    reconstructed_sum_count = 0
    decrease_count = 0
    running_sum = 0.0
    previous_sum: float | None = None
    for start, record in winners:
        if not _is_complete(record, start, bucket, now_utc):
            incomplete_count += 1
            continue
        if record.cumulative_gallons is None:
            reconstructed_sum_count += 1
            running_sum += record.usage_gallons
            sum_value = running_sum
        else:
            sum_value = record.cumulative_gallons
            if previous_sum is not None and sum_value < previous_sum:
                decrease_count += 1
            running_sum = sum_value
        previous_sum = sum_value
        statistics.append(
            StatisticData(
                start=start,
                state=record.usage_gallons,
                sum=sum_value,
            )
        )

    return HistoryBuildResult(
        bucket=bucket,
        statistics=tuple(statistics),
        collision_count=collision_count,
        incomplete_count=incomplete_count,
        reconstructed_sum_count=reconstructed_sum_count,
        decrease_count=decrease_count,
        invalid_count=invalid_count,
    )


def build_all_history_statistics(
    records_by_bucket: Mapping[str, tuple[UsageRecord, ...] | list[UsageRecord]],
    *,
    now: datetime | None = None,
) -> dict[str, HistoryBuildResult]:
    """Build all independent raw, daily, and monthly history series."""
    return {
        bucket: build_bucket_statistics(
            records_by_bucket.get(bucket, ()), bucket, now=now
        )
        for bucket in HISTORY_BUCKETS
    }


def statistic_metadata(config: Mapping[str, object], bucket: str) -> StatisticMetaData:
    """Return explicit HA metadata for one external water statistic series."""
    labels = {
        BUCKET_RAW: "raw hourly",
        BUCKET_DAILY: "daily",
        BUCKET_MONTHLY: "monthly",
    }
    if bucket not in labels:
        raise ValueError(f"Unsupported GetMyMeter history bucket: {bucket}")
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=f"GetMyMeter {labels[bucket]} history",
        source=DOMAIN,
        statistic_id=statistic_id(config, bucket),
        unit_class=VolumeConverter.UNIT_CLASS,
        unit_of_measurement=UnitOfVolume.GALLONS,
    )


class GetMyMeterHistoryWorker:
    """Replay complete portal payloads into three durable recorder series."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: GetMyMeterApi,
        coordinator: object | None = None,
    ) -> None:
        """Initialize the per-entry history worker."""
        self.hass = hass
        self.entry = entry
        self.api = api
        self._coordinator = coordinator
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._last_summary: dict[str, object] = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "status": "not_started",
            "buckets": {},
        }

    @property
    def diagnostics(self) -> dict[str, object]:
        """Return secret-free worker status."""
        return dict(self._last_summary)

    async def async_start(self, _hass: HomeAssistant | None = None) -> None:
        """Start the initial replay after Home Assistant has started."""
        if self._task and not self._task.done():
            return
        self._task = self.entry.async_create_background_task(
            self.hass,
            self._async_loop(),
            f"{DOMAIN}_history",
        )
        self._task.add_done_callback(self._task_done)

    def async_unload(self) -> None:
        """Cancel the replay loop when the config entry unloads."""
        if self._task and not self._task.done():
            self._task.cancel()

    def _task_done(self, task: asyncio.Task[None]) -> None:
        """Consume task completion without logging secret-bearing exceptions."""
        if task.cancelled():
            return
        if task.exception() is not None:
            LOGGER.error("GetMyMeter history worker stopped; it will restart on reload")

    async def _async_loop(self) -> None:
        """Replay all buckets and repeat at the integration polling cadence."""
        while True:
            await self.async_run()
            await asyncio.sleep(DEFAULT_SCAN_INTERVAL.total_seconds())

    async def async_run(self) -> None:
        """Fetch and replay each bucket independently."""
        async with self._lock:
            now = datetime.now(UTC)
            statuses: dict[str, dict[str, object]] = {}
            auth_failed = False
            for bucket in HISTORY_BUCKETS:
                try:
                    records = await self.api.async_fetch_bucket(bucket)
                except GetMyMeterAuthError:
                    auth_failed = True
                    statuses[bucket] = {"status": "auth_failed", "rows": 0}
                    LOGGER.warning(
                        "GetMyMeter history bucket %s needs reauthentication", bucket
                    )
                    continue
                except GetMyMeterApiError:
                    statuses[bucket] = {"status": "fetch_failed", "rows": 0}
                    LOGGER.warning(
                        "GetMyMeter history bucket %s will be retried", bucket
                    )
                    continue

                result = build_bucket_statistics(records, bucket, now=now)
                status = "no_complete_data"
                if result.statistics:
                    try:
                        async_add_external_statistics(
                            self.hass,
                            statistic_metadata(self.entry.data, bucket),
                            result.statistics,
                        )
                    except HomeAssistantError, RuntimeError:
                        status = "import_failed"
                        LOGGER.warning(
                            "GetMyMeter history bucket %s could not be queued", bucket
                        )
                    else:
                        status = "import_queued"
                statuses[bucket] = {
                    "status": status,
                    "rows": len(result.statistics),
                    "collisions": result.collision_count,
                    "incomplete": result.incomplete_count,
                    "reconstructed_sum": result.reconstructed_sum_count,
                    "decreases": result.decrease_count,
                    "invalid": result.invalid_count,
                }

            self._last_summary = {
                "schema_version": HISTORY_SCHEMA_VERSION,
                "status": (
                    "auth_failed"
                    if auth_failed
                    else "partial"
                    if any(
                        status["status"] in {"fetch_failed", "import_failed"}
                        for status in statuses.values()
                    )
                    else "complete"
                ),
                "buckets": statuses,
            }
            if auth_failed and self._coordinator is not None:
                request_refresh = getattr(
                    self._coordinator, "async_request_refresh", None
                )
                if request_refresh is not None:
                    request_refresh()
