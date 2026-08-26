"""The GetMyMeter integration."""

from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.start import async_at_started

from .api import GetMyMeterApi
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import GetMyMeterConfigEntry, GetMyMeterCoordinator
from .history import GetMyMeterHistoryWorker
from .identity import stable_entry_unique_id

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry[GetMyMeterCoordinator]
) -> bool:
    """Preserve token-only data while moving it into the credential reauth flow."""
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2, minor_version=1)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GetMyMeterConfigEntry) -> bool:
    """Set up GetMyMeter from a config entry."""
    if not entry.data.get(CONF_USERNAME) or not entry.data.get(CONF_PASSWORD):
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="reauth_required",
        )
    expected_unique_id = stable_entry_unique_id(entry.data)
    if entry.unique_id != expected_unique_id:
        hass.config_entries.async_update_entry(entry, unique_id=expected_unique_id)
    session = async_create_clientsession(hass, cookie_jar=CookieJar())
    api = GetMyMeterApi(session, entry.data)
    coordinator = GetMyMeterCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    history_worker = GetMyMeterHistoryWorker(hass, entry, api, coordinator)
    coordinator.history_worker = history_worker
    entry.async_on_unload(history_worker.async_unload)
    entry.async_on_unload(async_at_started(hass, history_worker.async_start))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry[GetMyMeterCoordinator]
) -> bool:
    """Unload a GetMyMeter config entry."""
    coordinator = entry.runtime_data
    if coordinator.history_worker is not None:
        coordinator.history_worker.async_unload()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
