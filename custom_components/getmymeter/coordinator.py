"""Data update coordinator for GetMyMeter."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GetMyMeterApi, GetMyMeterApiError, GetMyMeterAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER
from .parser import UsageRecord, latest_record


@dataclass(frozen=True, slots=True)
class GetMyMeterData:
    """Latest daily and monthly AMI samples."""

    daily: tuple[UsageRecord, ...]
    monthly: tuple[UsageRecord, ...]

    @property
    def latest_daily(self) -> UsageRecord | None:
        """Return the newest daily sample."""
        return latest_record(self.daily)

    @property
    def latest_monthly(self) -> UsageRecord | None:
        """Return the newest monthly sample."""
        return latest_record(self.monthly)


class GetMyMeterCoordinator(DataUpdateCoordinator[GetMyMeterData]):
    """Coordinate low-frequency read-only portal updates."""

    config_entry: GetMyMeterConfigEntry

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

    async def _async_update_data(self) -> GetMyMeterData:
        """Fetch daily and monthly usage from the read-only AMI endpoint."""
        try:
            daily = await self.api.async_fetch_bucket("d")
            monthly = await self.api.async_fetch_bucket("m")
        except GetMyMeterAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="reauth_required",
            ) from err
        except GetMyMeterApiError as err:
            raise UpdateFailed("Unable to fetch GetMyMeter data") from err

        if not daily:
            raise UpdateFailed("GetMyMeter returned no daily samples")
        return GetMyMeterData(daily=daily, monthly=monthly)


GetMyMeterConfigEntry = ConfigEntry[GetMyMeterCoordinator]
