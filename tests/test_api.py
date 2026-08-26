"""Authentication, discovery, and request-boundary tests."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.getmymeter.api import (
    GetMyMeterApi,
    GetMyMeterApiError,
    GetMyMeterAuthError,
    GetMyMeterConnectionError,
    GetMyMeterMeter,
)
from custom_components.getmymeter.const import API_ORIGIN

from .conftest import TEST_CONFIG

PERMUTATION = "A" * 32
PORTAL_TOKEN = "00000000-0000-0000-0000-000000000000"  # noqa: S105
LOGIN_HTML = f"""
<html><head><script src="/h2o_portal/{PERMUTATION}.cache.js"></script></head>
<body><div id="H2O-Portal-Token">{PORTAL_TOKEN}</div></body></html>
"""
LOGIN_HTML_WITH_BOOTSTRAP = f"""
<html><head><script src="/h2o_portal/h2o_portal.nocache.js"></script></head>
<body><div id="H2O-Portal-Token">{PORTAL_TOKEN}</div></body></html>
"""
BOOTSTRAP = f"function h2o_portal(){{var current='{PERMUTATION}';}}"
TRUSTED_SESSION = r"""//OK[39,0,38,37,-7,36,0,0,0,0,0,-7,35,-8,34,33,-7,32,31,30,29,28,27,26,25,0,-7,"FJlwA",24,0,0,23,0,0,0,0,-7,0,13,-7,0,-7,-8,-7,1,20,22,0,21,0,20,19,12,13,0,138,13,18,5,0,0,0,17,5,0,0,15,16,15,5,14,7,13,20,13,0,0,0,5,5,5,5,12,11,10,0,0,0,0,9,5,0,5,8,7,0,6,5,4,3,2,1,1,["java.util.ArrayList/4159755760","com.h2oanalytics.shared.TrustedSession/1943350601","synthetic-name","synthetic-portal-account","","synthetic-5","synthetic-6","synthetic-7","synthetic-8","synthetic-9","synthetic-10","synthetic-11","java.lang.Integer/3438268394","synthetic-13","synthetic-14","synthetic-15","synthetic-16","synthetic-17","synthetic-18","java.lang.Boolean/476441737","synthetic-20","synthetic-21","synthetic-22","java.lang.Long/4227064769","synthetic-24","synthetic-25","synthetic-26","synthetic-27","synthetic-28","synthetic-29","synthetic-30","synthetic-31","synthetic-32","synthetic-33","synthetic-34","synthetic-35","synthetic-36","synthetic-37","synthetic-38"],0,7]"""
METERS = '//OK[1,["synthetic-account|1|meter|address|true|true|true\\n"],0,7]'
AMI_DATA = "1704067200000|1|2|0|"


class FakeResponse:
    """Minimal async response context manager."""

    def __init__(
        self,
        status: int = 200,
        text: str = AMI_DATA,
        content_type: str = "text/plain",
    ) -> None:
        self.status = status
        self._text = text
        self.headers = {"Content-Type": content_type}

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def text(self) -> str:
        return self._text


class FakeSession:
    """Capture request options and return queued synthetic responses."""

    def __init__(
        self,
        *,
        gets: list[FakeResponse | BaseException] | None = None,
        posts: list[FakeResponse | BaseException] | None = None,
    ) -> None:
        self.gets = list(gets or [])
        self.posts = list(posts or [])
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    @staticmethod
    def _response(
        queue: list[FakeResponse | BaseException],
    ) -> FakeResponse:
        response = queue.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get(self, *args: object, **kwargs: object) -> FakeResponse:
        self.calls.append(("GET", args, kwargs))
        return self._response(self.gets)

    def post(self, *args: object, **kwargs: object) -> FakeResponse:
        self.calls.append(("POST", args, kwargs))
        return self._response(self.posts)


def authenticated_posts() -> list[FakeResponse]:
    """Return one complete synthetic login/token-check sequence."""
    return [
        FakeResponse(text=LOGIN_HTML, content_type="text/html"),
        FakeResponse(text=TRUSTED_SESSION, content_type="application/json"),
    ]


@pytest.mark.asyncio
async def test_username_password_discovers_meter_without_url_or_token() -> None:
    """Credentials alone discover the complete AMI meter identity."""
    session = FakeSession(
        posts=[
            *authenticated_posts(),
            FakeResponse(text=METERS, content_type="application/json"),
        ]
    )
    meters = await GetMyMeterApi(session, TEST_CONFIG).async_discover_meters()
    assert [(meter.company_id, meter.account, meter.channel) for meter in meters] == [
        ("138", "synthetic-account", "1")
    ]
    login = session.calls[0]
    assert login[0] == "POST"
    assert login[1][0] == f"{API_ORIGIN}/sp"
    assert login[2]["allow_redirects"] is False
    assert login[2]["data"]["username"] == TEST_CONFIG["username"]
    assert login[2]["data"]["password"] == TEST_CONFIG["password"]
    meter_call = session.calls[2]
    assert meter_call[1][0] == f"{API_ORIGIN}/h2o_portal/utilityservice"
    assert "synthetic-portal-account" in meter_call[2]["data"]


@pytest.mark.asyncio
async def test_login_resolves_permutation_from_public_bootstrap() -> None:
    """Raw login HTML need not contain the script injected by the browser."""
    session = FakeSession(
        posts=[
            FakeResponse(text=LOGIN_HTML_WITH_BOOTSTRAP, content_type="text/html"),
            FakeResponse(text=TRUSTED_SESSION, content_type="application/json"),
            FakeResponse(text=METERS, content_type="application/json"),
        ],
        gets=[FakeResponse(text=BOOTSTRAP, content_type="application/javascript")],
    )
    meters = await GetMyMeterApi(session, TEST_CONFIG).async_discover_meters()
    assert meters == (GetMyMeterMeter("138", "synthetic-account", "1"),)
    method, args, kwargs = session.calls[1]
    assert method == "GET"
    assert args[0] == f"{API_ORIGIN}/h2o_portal/h2o_portal.nocache.js"
    assert kwargs["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("bucket", ["r", "d", "m"])
async def test_fetch_logs_in_and_uses_fixed_origin(bucket: str) -> None:
    """A first fetch logs in and sends only a derived in-memory header."""
    session = FakeSession(
        posts=authenticated_posts(),
        gets=[FakeResponse()],
    )
    api = GetMyMeterApi(
        session,
        {
            **TEST_CONFIG,
            "company_id": "138",
            "account": "synthetic-account",
            "channel": "1",
            "base_url": "http://untrusted.invalid",
        },
    )
    await api.async_fetch_bucket(bucket)
    method, args, kwargs = session.calls[-1]
    assert method == "GET"
    assert args[0] == f"{API_ORIGIN}/ami_data"
    assert kwargs["params"]["b"] == bucket
    assert kwargs["headers"]["h2o-token"] == f"<token>{PORTAL_TOKEN}</token>"
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"].total == 30


@pytest.mark.asyncio
async def test_expired_session_relogs_in_and_retries_once() -> None:
    """An expired AMI session is renewed without a reauth flow."""
    session = FakeSession(
        posts=[*authenticated_posts(), *authenticated_posts()],
        gets=[
            FakeResponse(
                status=500, text="<html>expired</html>", content_type="text/html"
            ),
            FakeResponse(),
        ],
    )
    api = GetMyMeterApi(
        session,
        {
            **TEST_CONFIG,
            "company_id": "138",
            "account": "synthetic-account",
            "channel": "1",
        },
    )
    records = await api.async_fetch_bucket("d")
    assert len(records) == 1
    assert [method for method, _, _ in session.calls].count("GET") == 2
    assert [method for method, _, _ in session.calls].count("POST") == 4


@pytest.mark.asyncio
async def test_concurrent_expiry_does_not_replace_a_newer_session() -> None:
    """A waiter cannot log in again after another task already renewed the token."""
    api = GetMyMeterApi(FakeSession(), TEST_CONFIG)
    api._token = "new-session"  # noqa: S105
    with patch.object(api, "_async_start_session", new=AsyncMock()) as login:
        await api._async_refresh_session("expired-session")
    login.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_credentials_fail_without_response_or_secret_leakage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A login form response is classified as authentication failure."""
    session = FakeSession(
        posts=[
            FakeResponse(
                text="<html><form id='login'>invalid credentials</form></html>",
                content_type="text/html",
            )
        ]
    )
    with pytest.raises(GetMyMeterAuthError) as raised:
        await GetMyMeterApi(session, TEST_CONFIG).async_discover_meters()
    assert TEST_CONFIG["password"] not in str(raised.value)
    assert TEST_CONFIG["password"] not in caplog.text


@pytest.mark.asyncio
async def test_redirect_and_connection_failures_are_closed() -> None:
    """Credential redirects and connectivity failures do not silently continue."""
    redirect = FakeSession(posts=[FakeResponse(status=302)])
    with pytest.raises(GetMyMeterApiError):
        await GetMyMeterApi(redirect, TEST_CONFIG).async_discover_meters()

    offline = FakeSession(posts=[TimeoutError()])
    with pytest.raises(GetMyMeterConnectionError):
        await GetMyMeterApi(offline, TEST_CONFIG).async_discover_meters()


@pytest.mark.asyncio
async def test_missing_credentials_fail_before_request() -> None:
    """Legacy token-only entries require the one-time credential migration."""
    session = FakeSession()
    with pytest.raises(GetMyMeterAuthError):
        await GetMyMeterApi(session, {}).async_fetch_bucket("d")
    assert not session.calls
