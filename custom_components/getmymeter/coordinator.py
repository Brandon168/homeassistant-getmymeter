"""Data update coordinator for GetMyMeter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GetMyMeterApi, GetMyMeterApiError, GetMyMeterAuthError
from .const import (
    BUCKET_DAILY,
    BUCKET_MONTHLY,
    BUCKET_RAW,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
)
from .parser import UsageRecord, latest_record

if TYPE_CHECKING:
    from .history import GetMyMeterHistoryWorker


@dataclass(frozen=True, slots=True)
class GetMyMeterData:
    """Latest portal samples and non-fatal history fetch status."""

    raw: tuple[UsageRecord, ...]
    daily: tuple[UsageRecord, ...]
    monthly: tuple[UsageRecord, ...]
    history_failures: tuple[str, ...] = ()

    @property
    def latest_raw(self) -> UsageRecord | None:
        """Return the newest raw/hourly sample."""
        return latest_record(self.raw)

    @property
    def latest_daily(self) -> UsageRecord | None:
        """Return the newest daily sample."""
        return latest_record(self.daily)

    @property
    def latest_monthly(self) -> UsageRecord | None:
        """Return the newest monthly sample."""
        return latest_record(self.monthly)


class GetMyMeterCoordinator(DataUpdateCoordinator[GetMyMeterData]):
    """Coordinate read-only portal updates with daily data as the primary source."""

    config_entry: GetMyMeterConfigEntry
    history_worker: GetMyMeterHistoryWorker | None

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GetMyMeterConfigEntry,
        api: GetMyMeterApi,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.api = api
        self.history_worker = None
        self._history_cache: dict[str, tuple[UsageRecord, ...]] = {}

    async def _async_update_data(self) -> GetMyMeterData:
        """Fetch all three live buckets while keeping daily data primary."""
        try:
            daily = await self.api.async_fetch_bucket(BUCKET_DAILY)
        except GetMyMeterAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="reauth_required",
            ) from err
        except GetMyMeterApiError as err:
            raise UpdateFailed("Unable to fetch primary GetMyMeter daily data") from err

        self._history_cache[BUCKET_DAILY] = daily
        failures: list[str] = []
        buckets: dict[str, tuple[UsageRecord, ...]] = {BUCKET_DAILY: daily}
        for bucket in (BUCKET_RAW, BUCKET_MONTHLY):
            try:
                records = await self.api.async_fetch_bucket(bucket)
            except GetMyMeterAuthError as err:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="reauth_required",
                ) from err
            except GetMyMeterApiError:
                failures.append(bucket)
                LOGGER.warning(
                    "GetMyMeter %s data was unavailable; daily data remains usable",
                    bucket,
                )
                records = self._history_cache.get(bucket, ())
            else:
                self._history_cache[bucket] = records
            buckets[bucket] = records

        return GetMyMeterData(
            raw=buckets[BUCKET_RAW],
            daily=buckets[BUCKET_DAILY],
            monthly=buckets[BUCKET_MONTHLY],
            history_failures=tuple(failures),
        )


GetMyMeterConfigEntry = ConfigEntry[GetMyMeterCoordinator]
