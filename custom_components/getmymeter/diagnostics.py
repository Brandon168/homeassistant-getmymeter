"""Secret-safe diagnostics for GetMyMeter."""

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    API_ORIGIN,
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    CONF_TOKEN,
    REQUEST_TIMEOUT_SECONDS,
)
from .coordinator import GetMyMeterCoordinator

_REDACT_KEYS = {CONF_COMPANY_ID, CONF_ACCOUNT, CONF_CHANNEL, CONF_TOKEN}


def _bucket_snapshot(records: tuple[Any, ...]) -> dict[str, object]:
    """Return a count without exposing portal values or household timing."""
    return {"count": len(records)}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[GetMyMeterCoordinator]
) -> Mapping[str, Any]:
    """Return diagnostics that cannot disclose credentials or account data."""
    coordinator = entry.runtime_data
    data = coordinator.data
    safe_config = async_redact_data(
        {
            CONF_COMPANY_ID: entry.data.get(CONF_COMPANY_ID),
            CONF_ACCOUNT: entry.data.get(CONF_ACCOUNT),
            CONF_CHANNEL: entry.data.get(CONF_CHANNEL),
            CONF_TOKEN: entry.data.get(CONF_TOKEN),
        },
        _REDACT_KEYS,
    )
    history = (
        coordinator.history_worker.diagnostics if coordinator.history_worker else {}
    )
    return {
        "config": {
            "redacted": safe_config,
        },
        "api": {
            "origin": API_ORIGIN,
            "read_only": True,
            "allow_redirects": False,
            "timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        },
        "coordinator": {
            "available": coordinator.last_update_success,
            "history_failures": list(data.history_failures) if data else [],
            "buckets": {
                "raw": _bucket_snapshot(data.raw) if data else {"count": 0},
                "daily": _bucket_snapshot(data.daily) if data else {"count": 0},
                "monthly": _bucket_snapshot(data.monthly) if data else {"count": 0},
            },
        },
        "history": history,
    }
