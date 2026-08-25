"""Shared synthetic test helpers."""

from datetime import UTC, datetime

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder import migration as recorder_migration
from homeassistant.helpers import recorder as recorder_helper
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sqlalchemy.orm import Session

from custom_components.getmymeter.const import (
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.getmymeter.identity import stable_entry_unique_id

# HA 2026.8.3's wheel hides Recorder behind TYPE_CHECKING, but Python 3.14
# evaluates the annotation when the recorder test fixture creates an autospec.
recorder_migration.Recorder = Recorder
recorder_helper.Recorder = Recorder
recorder_helper.Session = Session

TEST_CONFIG = {
    CONF_COMPANY_ID: "synthetic-company",
    CONF_ACCOUNT: "synthetic-account",
    CONF_CHANNEL: "synthetic-channel",
    CONF_TOKEN: "synthetic-token-value",
}


def timestamp_ms(value: datetime) -> int:
    """Convert an aware synthetic datetime to epoch milliseconds."""
    return int(value.timestamp() * 1000)


def record_text(value: datetime, usage: float, cumulative: float | None) -> str:
    """Build one synthetic AMI row."""
    cumulative_text = "" if cumulative is None else str(cumulative)
    return f"{timestamp_ms(value)}|{usage}|{cumulative_text}|0|"


def make_entry(**overrides: str) -> MockConfigEntry:
    """Return a stable synthetic config entry."""
    data = {**TEST_CONFIG, **overrides}
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        unique_id=stable_entry_unique_id(data),
        title="Synthetic GetMyMeter",
    )


NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)
