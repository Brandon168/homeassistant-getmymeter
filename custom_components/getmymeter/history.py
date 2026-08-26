"""Deterministic external-statistics replay for GetMyMeter."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

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
    FULL_REPLAY_INTERVAL_CYCLES,
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


def _source_datetime(record: UsageRecord, source_timezone: tzinfo) -> datetime:
    """Return a portal wall-clock timestamp converted to UTC."""
    return record.timestamp_in(source_timezone)


def canonical_start(
    record: UsageRecord,
    bucket: str | None = None,
    *,
    source_timezone: tzinfo = UTC,
) -> datetime:
    """Map a portal record to a deterministic UTC top-of-hour start.

    Raw boundary markers at ``xx:59:59`` are treated as the end of that hour,
    then moved to the following hour before flooring. Daily and monthly rows
    represent their source-local calendar period and use that period's start.
    """
    bucket = bucket or record.bucket
    if bucket == BUCKET_RAW:
        source = _source_datetime(record, source_timezone)
        if source.minute == 59 and source.second == 59 and source.microsecond == 0:
            source += timedelta(seconds=1)
        return source.replace(minute=0, second=0, microsecond=0)
    wall_clock = record.timestamp_datetime.replace(tzinfo=None)
    if bucket == BUCKET_DAILY:
        local_start = wall_clock.replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=source_timezone
        )
        return local_start.astimezone(UTC)
    if bucket == BUCKET_MONTHLY:
        local_start = wall_clock.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=source_timezone,
        )
        return local_start.astimezone(UTC)
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
    record: UsageRecord,
    start: datetime,
    bucket: str,
    now: datetime,
    source_timezone: tzinfo,
) -> bool:
    """Apply the explicit incomplete-period publication policy."""
    source = _source_datetime(record, source_timezone)
    if bucket == BUCKET_RAW and source.minute == 59 and source.second == 59:
        return source <= now
    return _period_end(start, bucket) <= now


def build_bucket_statistics(  # noqa: PLR0913
    records: tuple[UsageRecord, ...] | list[UsageRecord],
    bucket: str,
    *,
    now: datetime | None = None,
    min_start: datetime | None = None,
    previous_sum: float | None = None,
    source_timezone: tzinfo = UTC,
) -> HistoryBuildResult:
    """Build one bucket without network or recorder side effects.

    Rows are sorted by canonical start. If several source records map to the
    same start, the latest source timestamp wins; an equal timestamp uses the
    last input row. Missing cumulative values use a deterministic reconstructed
    running sum and are counted for diagnostics. Source cumulative decreases
    are preserved rather than clamped.

    ``min_start`` drops rows whose canonical start is not newer than the given
    boundary, and ``previous_sum`` seeds the reconstructed running sum, so an
    incremental batch continues the cumulative series already in the recorder.
    """
    if bucket not in HISTORY_BUCKETS:
        raise ValueError(f"Unsupported GetMyMeter history bucket: {bucket}")
    now_utc = _as_utc(now or datetime.now(UTC))
    if min_start is not None:
        min_start = _as_utc(min_start)

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
            start = canonical_start(record, bucket, source_timezone=source_timezone)
        except OverflowError, OSError, ValueError:
            invalid_count += 1
            continue
        if min_start is not None and start <= min_start:
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
    running_sum = previous_sum if previous_sum is not None else 0.0
    previous = previous_sum
    for start, record in winners:
        if not _is_complete(record, start, bucket, now_utc, source_timezone):
            incomplete_count += 1
            continue
        if record.cumulative_gallons is None:
            reconstructed_sum_count += 1
            running_sum += record.usage_gallons
            sum_value = running_sum
        else:
            sum_value = record.cumulative_gallons
            if previous is not None and sum_value < previous:
                decrease_count += 1
            running_sum = sum_value
        previous = sum_value
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
    source_timezone: tzinfo = UTC,
) -> dict[str, HistoryBuildResult]:
    """Build all independent raw, daily, and monthly history series."""
    return {
        bucket: build_bucket_statistics(
            records_by_bucket.get(bucket, ()),
            bucket,
            now=now,
            source_timezone=source_timezone,
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
    """Replay portal payloads into three durable recorder series.

    The first run and every ``FULL_REPLAY_INTERVAL_CYCLES`` runs rebuild the
    complete series so retroactive portal corrections converge. Runs in between
    import only rows newer than the last queued period, seeded with the last
    queued cumulative sum so reconstructed sums stay continuous.
    """

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
        self._source_timezone = ZoneInfo(hass.config.time_zone)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._last_start: dict[str, datetime] = {}
        self._last_sum: dict[str, float] = {}
        self._cycles_since_full_replay = 0
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
        """Run one replay cycle, full or incremental, under the worker lock."""
        async with self._lock:
            full_replay = self._cycles_since_full_replay == 0
            await self._run_once(full_replay=full_replay)
            self._cycles_since_full_replay = (
                self._cycles_since_full_replay + 1
            ) % FULL_REPLAY_INTERVAL_CYCLES

    async def _run_once(self, *, full_replay: bool) -> None:
        """Fetch each bucket and queue only the rows this cycle needs."""
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
                LOGGER.warning("GetMyMeter history bucket %s will be retried", bucket)
                continue

            if full_replay:
                result = build_bucket_statistics(
                    records,
                    bucket,
                    now=now,
                    source_timezone=self._source_timezone,
                )
            else:
                result = build_bucket_statistics(
                    records,
                    bucket,
                    now=now,
                    min_start=self._last_start.get(bucket),
                    previous_sum=self._last_sum.get(bucket),
                    source_timezone=self._source_timezone,
                )
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
                    self._last_start[bucket] = result.statistics[-1]["start"]
                    self._last_sum[bucket] = result.statistics[-1]["sum"]
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
            "mode": "full" if full_replay else "incremental",
            "buckets": statuses,
        }
        if auth_failed and self._coordinator is not None:
            request_refresh = getattr(self._coordinator, "async_request_refresh", None)
            if request_refresh is not None:
                request_refresh()
