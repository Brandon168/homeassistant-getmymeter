"""Authenticated read-only H2O Analytics client used by GetMyMeter."""

import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from html import unescape

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    AMI_PATH,
    API_ORIGIN,
    CONF_ACCOUNT,
    CONF_CHANNEL,
    CONF_COMPANY_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_CHANNEL,
    DEFAULT_COMPANY_ID,
    DEFAULT_REFERER,
    GWT_BOOTSTRAP_PATH,
    GWT_MODULE_PATH,
    LOGIN_PATH,
    REQUEST_TIMEOUT_SECONDS,
    TOKEN_CHECK_PATH,
    UTILITY_SERVICE_PATH,
)
from .parser import BUCKETS, UsageRecord, parse_ami_data

_LOGIN_TOKEN_RE = re.compile(
    r'<[^>]+id=["\']H2O-Portal-Token["\'][^>]*>([^<]+)</', re.IGNORECASE
)
_PERMUTATION_RE = re.compile(r"/([A-F0-9]{32})\.cache\.js", re.IGNORECASE)
_BOOTSTRAP_PERMUTATION_RE = re.compile(r"[A-F0-9]{32}", re.IGNORECASE)
_GWT_STRING = "java.lang.String/2004016611"
_GWT_BOOLEAN = "java.lang.Boolean/476441737"
_GWT_INTEGER = "java.lang.Integer/3438268394"
_TRUSTED_SESSION_TYPE = "com.h2oanalytics.shared.TrustedSession/1943350601"


class GetMyMeterApiError(Exception):
    """Base exception for portal API failures."""


class GetMyMeterAuthError(GetMyMeterApiError):
    """Raised when credentials or the authenticated session are rejected."""


class GetMyMeterConnectionError(GetMyMeterApiError):
    """Raised when the portal cannot be reached."""


@dataclass(frozen=True, slots=True)
class GetMyMeterMeter:
    """A meter identity discovered from the authenticated portal."""

    company_id: str
    account: str
    channel: str


@dataclass(frozen=True, slots=True)
class _PortalSession:
    """The minimum trusted-session data required for meter discovery."""

    token: str
    permutation: str
    company_id: str
    portal_account: str


class GetMyMeterApi:
    """Read-only portal client with transparent session renewal."""

    def __init__(self, session: ClientSession, config: Mapping[str, object]) -> None:
        """Initialize the client from config-entry data."""
        self._session = session
        self.company_id = str(config.get(CONF_COMPANY_ID, DEFAULT_COMPANY_ID))
        self.account = str(config.get(CONF_ACCOUNT, ""))
        self.channel = str(config.get(CONF_CHANNEL, DEFAULT_CHANNEL))
        self._username = str(config.get(CONF_USERNAME, ""))
        self._password = str(config.get(CONF_PASSWORD, ""))
        self._token = ""
        self._timeout = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        self._auth_lock = asyncio.Lock()

    @property
    def has_credentials(self) -> bool:
        """Return whether persistent login credentials are configured."""
        return bool(self._username and self._password)

    def _params(self, bucket: str) -> dict[str, str]:
        """Build the observed AMI query without putting credentials in the URL."""
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

    @staticmethod
    def _gwt_headers(permutation: str) -> dict[str, str]:
        """Return the fixed headers required by the portal's GWT-RPC endpoint."""
        module_base = f"{API_ORIGIN}{GWT_MODULE_PATH}"
        return {
            "Content-Type": "text/x-gwt-rpc; charset=utf-8",
            "X-GWT-Module-Base": module_base,
            "X-GWT-Permutation": permutation,
        }

    async def _async_post_text(
        self,
        url: str,
        *,
        data: Mapping[str, str] | str,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> str:
        """POST to an allowlisted portal endpoint and return text."""
        try:
            async with self._session.post(
                url,
                data=data,
                headers=headers,
                params=params,
                allow_redirects=False,
                timeout=self._timeout,
            ) as response:
                if response.status in range(300, 400):
                    raise GetMyMeterApiError(
                        "The portal returned an unexpected redirect"
                    )
                if response.status != 200:
                    raise GetMyMeterApiError(
                        f"The portal returned HTTP {response.status}"
                    )
                return await response.text()
        except GetMyMeterApiError:
            raise
        except ClientError, TimeoutError:
            raise GetMyMeterConnectionError(
                "Unable to reach the GetMyMeter portal"
            ) from None
        except UnicodeError:
            raise GetMyMeterApiError("The portal returned invalid text") from None

    async def _async_get_public_text(self, url: str) -> str:
        """Fetch one fixed, non-authenticated portal bootstrap resource."""
        try:
            async with self._session.get(
                url,
                allow_redirects=False,
                timeout=self._timeout,
            ) as response:
                if response.status != 200:
                    raise GetMyMeterApiError(
                        f"The portal returned HTTP {response.status} for bootstrap"
                    )
                return await response.text()
        except GetMyMeterApiError:
            raise
        except ClientError, TimeoutError:
            raise GetMyMeterConnectionError(
                "Unable to reach the GetMyMeter portal"
            ) from None

    @staticmethod
    def _parse_gwt_response(text: str) -> tuple[list[object], list[str]]:
        """Return the value stream and string table from a GWT response."""
        if not text.startswith("//OK"):
            if text.startswith("//EX"):
                raise GetMyMeterAuthError("The portal rejected the session")
            raise GetMyMeterApiError("The portal returned invalid GWT data")
        try:
            data = json.loads(text[4:])
        except TypeError, ValueError:
            raise GetMyMeterApiError("The portal returned invalid GWT data") from None
        if (
            not isinstance(data, list)
            or len(data) < 3
            or not isinstance(data[-3], list)
            or data[-1] != 7
        ):
            raise GetMyMeterApiError("The portal returned invalid GWT data")
        table = data[-3]
        if not all(isinstance(value, str) for value in table):
            raise GetMyMeterApiError("The portal returned invalid GWT data")
        return data[:-3], table

    @classmethod
    def _parse_trusted_session(cls, text: str) -> tuple[str, str]:
        """Extract the portal account and company ID from TrustedSession."""
        stream, table = cls._parse_gwt_response(text)

        def pop_int() -> int:
            if not stream:
                raise GetMyMeterApiError("The portal session data is incomplete")
            value = stream.pop()
            if not isinstance(value, int) or isinstance(value, bool):
                raise GetMyMeterApiError("The portal session data is invalid")
            return value

        def read_string() -> str | None:
            index = pop_int()
            if index == 0:
                return None
            if index < 0 or index > len(table):
                raise GetMyMeterApiError("The portal session data is invalid")
            return table[index - 1]

        def read_scalar_object() -> int | bool | None:
            index = pop_int()
            if index <= 0:
                return None
            if index > len(table):
                raise GetMyMeterApiError("The portal session data is invalid")
            type_name = table[index - 1]
            if type_name.startswith("java.lang.Integer/"):
                return pop_int()
            if type_name.startswith("java.lang.Boolean/"):
                return bool(pop_int())
            raise GetMyMeterApiError("The portal session schema is unsupported")

        root_type = read_string()
        if not root_type or not root_type.startswith("java.util.ArrayList/"):
            raise GetMyMeterApiError("The portal session list is invalid")
        if pop_int() < 1:
            raise GetMyMeterAuthError("The portal returned no authenticated account")
        session_type = read_string()
        if session_type != _TRUSTED_SESSION_TYPE:
            raise GetMyMeterApiError("The portal session type is invalid")

        first_fields = [read_string() for _ in range(25)]
        portal_account = first_fields[1]
        read_scalar_object()
        read_scalar_object()
        for _ in range(14):
            read_string()
        company_id = read_scalar_object()
        if not portal_account or not isinstance(company_id, int) or company_id <= 0:
            raise GetMyMeterApiError("The portal account identity is incomplete")
        return portal_account, str(company_id)

    async def _async_start_session(self) -> _PortalSession:
        """Log in and obtain a fresh portal session."""
        if not self.has_credentials:
            raise GetMyMeterAuthError("GetMyMeter login credentials are required")
        html = await self._async_post_text(
            f"{API_ORIGIN}{LOGIN_PATH}",
            params={"cls": "cp", "action": "login", "locale": "en", "w": "1280"},
            data={
                CONF_USERNAME: self._username,
                CONF_PASSWORD: self._password,
                "device-uuid": "",
            },
            headers={"Referer": DEFAULT_REFERER},
        )
        token_match = _LOGIN_TOKEN_RE.search(html)
        permutation_match = _PERMUTATION_RE.search(html)
        if token_match is None:
            if "login" in html[:8192].casefold():
                raise GetMyMeterAuthError("The portal rejected the login credentials")
            raise GetMyMeterApiError("The portal login response is unsupported")
        token = unescape(token_match.group(1)).strip()
        permutation = permutation_match.group(1) if permutation_match else None
        if permutation is None:
            bootstrap = await self._async_get_public_text(
                f"{API_ORIGIN}{GWT_BOOTSTRAP_PATH}"
            )
            bootstrap_match = _BOOTSTRAP_PERMUTATION_RE.search(bootstrap)
            if bootstrap_match is None:
                raise GetMyMeterApiError("The portal bootstrap is unsupported")
            permutation = bootstrap_match.group(0)
        permutation = permutation.upper()
        if not token or len(permutation) != 32:
            raise GetMyMeterApiError("The portal login response is incomplete")

        module_base = f"{API_ORIGIN}{GWT_MODULE_PATH}"
        strings = [
            module_base,
            permutation,
            "com.h2oanalytics.client.TokenCheckService",
            "TokenCheckServer",
            _GWT_STRING,
            _GWT_BOOLEAN,
            token,
        ]
        body = f"7|0|7|{'|'.join(strings)}|1|2|3|4|2|5|6|7|6|1|"
        response = await self._async_post_text(
            f"{API_ORIGIN}{TOKEN_CHECK_PATH}",
            data=body,
            headers=self._gwt_headers(permutation),
        )
        portal_account, company_id = self._parse_trusted_session(response)
        return _PortalSession(token, permutation, company_id, portal_account)

    async def async_discover_meters(self) -> tuple[GetMyMeterMeter, ...]:
        """Log in and discover every meter available to the account."""
        async with self._auth_lock:
            portal = await self._async_start_session()
            self._token = f"<token>{portal.token}</token>"

        module_base = f"{API_ORIGIN}{GWT_MODULE_PATH}"
        strings = [
            module_base,
            portal.permutation,
            "com.h2oanalytics.widgets.client.UsageChartService",
            "getAMIMeters",
            _GWT_INTEGER,
            _GWT_STRING,
            portal.portal_account,
        ]
        body = f"7|0|7|{'|'.join(strings)}|1|2|3|4|3|5|6|6|5|{portal.company_id}|7|0|"
        response = await self._async_post_text(
            f"{API_ORIGIN}{UTILITY_SERVICE_PATH}",
            data=body,
            headers=self._gwt_headers(portal.permutation),
        )
        _, table = self._parse_gwt_response(response)
        meters: list[GetMyMeterMeter] = []
        for value in table:
            for line in value.splitlines():
                fields = line.strip().split("|")
                if len(fields) < 7 or fields[-3:] != ["true", "true", "true"]:
                    continue
                account, channel = fields[0].strip(), fields[1].strip()
                if account and channel:
                    meters.append(GetMyMeterMeter(portal.company_id, account, channel))
        unique = tuple(dict.fromkeys(meters))
        if not unique:
            raise GetMyMeterApiError("The portal returned no usable meters")
        return unique

    async def _async_refresh_session(self, rejected_token: str | None = None) -> None:
        """Replace the in-memory API token with a fresh login session."""
        async with self._auth_lock:
            if rejected_token is not None and self._token != rejected_token:
                return
            portal = await self._async_start_session()
            self._token = f"<token>{portal.token}</token>"

    async def _async_fetch_bucket_once(
        self, bucket: str, token: str
    ) -> tuple[UsageRecord, ...]:
        """Fetch one read-only AMI bucket with the current session."""
        try:
            async with self._session.get(
                f"{API_ORIGIN}{AMI_PATH}",
                params=self._params(bucket),
                headers={
                    "Accept": "text/plain",
                    "h2o-token": token,
                    "Referer": DEFAULT_REFERER,
                },
                allow_redirects=False,
                timeout=self._timeout,
            ) as response:
                content_type = response.headers.get("Content-Type", "")
                if response.status in (401, 403):
                    raise GetMyMeterAuthError("The portal rejected the session")
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

    async def async_fetch_bucket(self, bucket: str) -> tuple[UsageRecord, ...]:
        """Fetch a bucket and transparently log in again after session expiry."""
        if not self._token:
            await self._async_refresh_session()
        request_token = self._token
        try:
            return await self._async_fetch_bucket_once(bucket, request_token)
        except GetMyMeterAuthError:
            await self._async_refresh_session(request_token)
            return await self._async_fetch_bucket_once(bucket, self._token)
