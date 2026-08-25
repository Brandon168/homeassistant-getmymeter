"""Constants for the GetMyMeter integration."""

import logging
from datetime import timedelta

from homeassistant.const import CONF_TOKEN

DOMAIN = "getmymeter"
INTEGRATION_TITLE = "GetMyMeter"
API_ORIGIN = "https://h2o-analytics.appspot.com"
AMI_PATH = "/ami_data"
DEFAULT_COMPANY_ID = "138"
DEFAULT_CHANNEL = "1"
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)
DEFAULT_REFERER = "https://getmymeter.info/"
REQUEST_TIMEOUT_SECONDS = 30.0
HISTORY_SCHEMA_VERSION = 1
FULL_REPLAY_INTERVAL_CYCLES = 4

CONF_COMPANY_ID = "company_id"
CONF_ACCOUNT = "account"
CONF_CHANNEL = "channel"

BUCKET_RAW = "r"
BUCKET_DAILY = "d"
BUCKET_MONTHLY = "m"
HISTORY_BUCKETS = (BUCKET_RAW, BUCKET_DAILY, BUCKET_MONTHLY)

ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_UNKNOWN = "unknown"

LOGGER = logging.getLogger(__package__)

__all__ = [
    "AMI_PATH",
    "API_ORIGIN",
    "BUCKET_DAILY",
    "BUCKET_MONTHLY",
    "BUCKET_RAW",
    "CONF_ACCOUNT",
    "CONF_CHANNEL",
    "CONF_COMPANY_ID",
    "CONF_TOKEN",
    "DEFAULT_CHANNEL",
    "DEFAULT_COMPANY_ID",
    "DEFAULT_REFERER",
    "DEFAULT_SCAN_INTERVAL",
    "DOMAIN",
    "ERROR_CANNOT_CONNECT",
    "ERROR_INVALID_AUTH",
    "ERROR_UNKNOWN",
    "FULL_REPLAY_INTERVAL_CYCLES",
    "HISTORY_BUCKETS",
    "HISTORY_SCHEMA_VERSION",
    "INTEGRATION_TITLE",
    "LOGGER",
    "REQUEST_TIMEOUT_SECONDS",
]
