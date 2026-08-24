"""Read-only H2O Analytics requests used by GetMyMeter."""

from collections.abc import Mapping

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    AMI_PATH,
    API_ORIGIN,
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    CONF_TOKEN,
    DEFAULT_CHANNEL,
    DEFAULT_COMPANY_ID,
    DEFAULT_REFERER,
    REQUEST_TIMEOUT_SECONDS,
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
        self.company_id = str(config.get(CONF_COMPANY_ID, DEFAULT_COMPANY_ID))
        self.account = str(config.get(CONF_ACCOUNT, ""))
        self.channel = str(config.get(CONF_CHANNEL, DEFAULT_CHANNEL))
        self.token = str(config.get(CONF_TOKEN, ""))
        self._timeout = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)

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

    @staticmethod
    def _is_authentication_html(text: str, content_type: str) -> bool:
        """Recognize a portal login page without retaining or exposing its body."""
        sample = text[:4096].casefold()
        if "html" not in content_type.casefold() and not sample.lstrip().startswith(
            ("<!doctype", "<html")
        ):
            return False
        return any(
            marker in sample
            for marker in (
                "login",
                "log in",
                "sign in",
                "signin",
                "session expired",
                "unauthorized",
                "authentication required",
            )
        )

    async def async_fetch_bucket(self, bucket: str) -> tuple[UsageRecord, ...]:
        """Fetch one read-only AMI bucket."""
        if not self.token:
            raise GetMyMeterAuthError("The GetMyMeter portal token is empty")

        try:
            async with self._session.get(
                f"{API_ORIGIN}{AMI_PATH}",
                params=self._params(bucket),
                headers={
                    "Accept": "text/plain",
                    "h2o-token": self.token,
                    "Referer": DEFAULT_REFERER,
                },
                allow_redirects=False,
                timeout=self._timeout,
            ) as response:
                content_type = response.headers.get("Content-Type", "")
                if response.status in (401, 403):
                    raise GetMyMeterAuthError(
                        f"The portal rejected the {BUCKETS[bucket]} token"
                    )
                if response.status in range(300, 400):
                    raise GetMyMeterApiError(
                        "The portal returned an unexpected redirect"
                    )
                if response.status != 200:
                    if response.status == 500 and "html" in content_type.casefold():
                        await response.text()
                        raise GetMyMeterAuthError(
                            "The portal rejected the authenticated session"
                        )
                    raise GetMyMeterApiError(
                        f"The portal returned HTTP {response.status} for AMI data"
                    )
                text = await response.text()
                if self._is_authentication_html(text, content_type):
                    raise GetMyMeterAuthError(
                        "The portal returned an authentication page"
                    )
                if "html" in content_type.casefold() or text.lstrip().startswith(
                    ("<!doctype", "<html")
                ):
                    raise GetMyMeterApiError(
                        "The portal returned an unexpected HTML response"
                    )
        except GetMyMeterApiError:
            raise
        except ClientError, TimeoutError:
            raise GetMyMeterConnectionError(
                "Unable to reach the GetMyMeter portal"
            ) from None
        except UnicodeError, ValueError:
            raise GetMyMeterApiError("The portal returned invalid AMI data") from None

        try:
            return parse_ami_data(text, bucket)
        except ValueError:
            raise GetMyMeterApiError("The portal returned invalid AMI data") from None
