"""The GetMyMeter integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GetMyMeterApi
from .coordinator import GetMyMeterConfigEntry, GetMyMeterCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: GetMyMeterConfigEntry) -> bool:
    """Set up GetMyMeter from a config entry."""
    session = async_get_clientsession(hass)
    api = GetMyMeterApi(session, entry.data)
    coordinator = GetMyMeterCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry[GetMyMeterCoordinator]
) -> bool:
    """Unload a GetMyMeter config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
