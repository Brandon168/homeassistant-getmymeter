"""Read-only H2O Analytics requests used by GetMyMeter."""

from collections.abc import Mapping

from aiohttp import ClientError, ClientSession

from .const import (
    CONF_ACCOUNT,
    CONF_BASE_URL,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    CONF_TOKEN,
    DEFAULT_BASE_URL,
    DEFAULT_CHANNEL,
    DEFAULT_COMPANY_ID,
    DEFAULT_REFERER,
)
from .parser import BUCKETS, UsageRecord, parse_ami_data


class GetMyMeterApiError(Exception):
    """Base exception for portal API failures."""


class GetMyMeterAuthError(GetMyMeterApiError):
    """Raised when the portal token is rejected or has expired."""


class GetMyMeterConnectionError(GetMyMeterApiError):
    """Raised when the portal cannot be reached."""


class GetMyMeterApi:
    """Minimal read-only client for the observed AMI endpoint."""

    def __init__(self, session: ClientSession, config: Mapping[str, object]) -> None:
        """Initialize the client from config-entry data."""
        self._session = session
        self.base_url = str(config.get(CONF_BASE_URL, DEFAULT_BASE_URL)).rstrip("/")
        self.company_id = str(config.get(CONF_COMPANY_ID, DEFAULT_COMPANY_ID))
        self.account = str(config.get(CONF_ACCOUNT, ""))
        self.channel = str(config.get(CONF_CHANNEL, DEFAULT_CHANNEL))
        self.token = str(config.get(CONF_TOKEN, ""))

    def _params(self, bucket: str) -> dict[str, str]:
        """Build the observed AMI query without putting the token in the URL."""
        if bucket not in BUCKETS:
            raise ValueError(f"bucket must be one of {sorted(BUCKETS)}")
        if not self.account:
            raise ValueError("A GetMyMeter account identifier is required")
        return {
            "cid": self.company_id,
            "l": self.account,
            "c": self.channel,
            "b": bucket,
            "df": "false",
            "r": "0",
        }

    async def async_fetch_bucket(self, bucket: str) -> tuple[UsageRecord, ...]:
        """Fetch one read-only AMI bucket."""
        if not self.token:
            raise GetMyMeterAuthError("The GetMyMeter portal token is empty")

        try:
            async with self._session.get(
                f"{self.base_url}/ami_data",
                params=self._params(bucket),
                headers={
                    "Accept": "text/plain",
                    "h2o-token": self.token,
                    "Referer": DEFAULT_REFERER,
                },
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise GetMyMeterAuthError(
                        f"The portal rejected the {BUCKETS[bucket]} token"
                    )
                if response.status != 200:
                    raise GetMyMeterApiError(
                        f"The portal returned HTTP {response.status} for AMI data"
                    )
                text = await response.text()
        except GetMyMeterApiError:
            raise
        except (ClientError, TimeoutError) as err:
            raise GetMyMeterConnectionError(
                "Unable to reach the GetMyMeter portal"
            ) from err

        try:
            return parse_ami_data(text, bucket)
        except ValueError as err:
            raise GetMyMeterApiError("The portal returned invalid AMI data") from err
