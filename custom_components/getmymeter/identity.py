"""Stable, non-identifying GetMyMeter identifiers."""

import hashlib
from collections.abc import Mapping

from .const import (
    BUCKET_DAILY,
    BUCKET_MONTHLY,
    BUCKET_RAW,
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    DEFAULT_CHANNEL,
    DEFAULT_COMPANY_ID,
    DOMAIN,
)

_IDENTITY_SEPARATOR = "\x1f"
_BUCKET_SUFFIXES = {
    BUCKET_RAW: "raw",
    BUCKET_DAILY: "daily",
    BUCKET_MONTHLY: "monthly",
}
_IDENTITY_KEYS = (CONF_COMPANY_ID, CONF_ACCOUNT, CONF_CHANNEL)


def identity_hash(data: Mapping[str, object]) -> str:
    """Return a stable SHA-256 digest for the meter identity.

    The exact configured company, account, and channel strings are joined with
    a non-printing separator before hashing. The token and config-entry UUID are
    deliberately not part of the input.
    """
    values = (
        str(data.get(CONF_COMPANY_ID, DEFAULT_COMPANY_ID)),
        str(data.get(CONF_ACCOUNT, "")),
        str(data.get(CONF_CHANNEL, DEFAULT_CHANNEL)),
    )
    return hashlib.sha256(_IDENTITY_SEPARATOR.join(values).encode("utf-8")).hexdigest()


def stable_entry_unique_id(data: Mapping[str, object]) -> str:
    """Return the stable config-entry unique ID for a meter channel."""
    return f"meter_{identity_hash(data)}"


def statistic_id(data: Mapping[str, object], bucket: str) -> str:
    """Return the external statistic ID for one history bucket."""
    if bucket not in _BUCKET_SUFFIXES:
        raise ValueError(f"Unsupported GetMyMeter history bucket: {bucket}")
    return f"{DOMAIN}:meter_{identity_hash(data)}_{_BUCKET_SUFFIXES[bucket]}"


def identity_keys() -> tuple[str, str, str]:
    """Return the identity field names for diagnostics and documentation."""
    return _IDENTITY_KEYS
