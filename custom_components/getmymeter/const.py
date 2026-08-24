"""Constants for the GetMyMeter integration."""

import logging
from datetime import timedelta

from homeassistant.const import CONF_TOKEN

DOMAIN = "getmymeter"
INTEGRATION_TITLE = "GetMyMeter"
DEFAULT_BASE_URL = "https://h2o-analytics.appspot.com"
DEFAULT_COMPANY_ID = "138"
DEFAULT_CHANNEL = "1"
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)
DEFAULT_REFERER = "https://getmymeter.info/"

CONF_BASE_URL = "base_url"
CONF_COMPANY_ID = "company_id"
CONF_ACCOUNT = "account"
CONF_CHANNEL = "channel"

ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_UNKNOWN = "unknown"

LOGGER = logging.getLogger(__package__)

__all__ = [
    "CONF_ACCOUNT",
    "CONF_BASE_URL",
    "CONF_CHANNEL",
    "CONF_COMPANY_ID",
    "CONF_TOKEN",
    "DEFAULT_BASE_URL",
    "DEFAULT_CHANNEL",
    "DEFAULT_COMPANY_ID",
    "DEFAULT_REFERER",
    "DEFAULT_SCAN_INTERVAL",
    "DOMAIN",
    "ERROR_CANNOT_CONNECT",
    "ERROR_INVALID_AUTH",
    "ERROR_UNKNOWN",
    "INTEGRATION_TITLE",
    "LOGGER",
]
