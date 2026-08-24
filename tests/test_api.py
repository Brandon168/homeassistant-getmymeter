"""Request-boundary and authentication tests."""

import pytest

from custom_components.getmymeter.api import (
    GetMyMeterApi,
    GetMyMeterApiError,
    GetMyMeterAuthError,
    GetMyMeterConnectionError,
)
from custom_components.getmymeter.const import API_ORIGIN, CONF_TOKEN

from .conftest import TEST_CONFIG


class FakeResponse:
    """Minimal async response context manager."""

    def __init__(
        self,
        status: int = 200,
        text: str = "1704067200000|1|2|0|",
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
    """Capture request options without network access."""

    def __init__(self, response: FakeResponse | BaseException) -> None:
        self.response = response
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def get(self, *args: object, **kwargs: object) -> FakeResponse:
        self.calls.append((args, kwargs))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize("bucket", ["r", "d", "m"])
async def test_all_buckets_use_fixed_origin_and_header_token(bucket: str) -> None:
    """Every bucket request is read-only and keeps the token out of the URL."""
    session = FakeSession(FakeResponse())
    api = GetMyMeterApi(
        session, {**TEST_CONFIG, "base_url": "http://untrusted.invalid"}
    )
    await api.async_fetch_bucket(bucket)
    args, kwargs = session.calls[0]
    assert args[0] == f"{API_ORIGIN}/ami_data"
    assert kwargs["params"]["b"] == bucket
    assert kwargs["headers"]["h2o-token"] == TEST_CONFIG[CONF_TOKEN]
    assert TEST_CONFIG[CONF_TOKEN] not in str(args[0])
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"].total == 30


@pytest.mark.asyncio
async def test_auth_html_is_classified_without_body_or_token_leakage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 200 login page becomes auth failure without retaining response text."""
    token = TEST_CONFIG[CONF_TOKEN]
    session = FakeSession(
        FakeResponse(
            text=f"<html><body>login {token}</body></html>", content_type="text/html"
        )
    )
    with pytest.raises(GetMyMeterAuthError) as raised:
        await GetMyMeterApi(session, TEST_CONFIG).async_fetch_bucket("d")
    assert token not in str(raised.value)
    assert token not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "exception"),
    [
        (FakeResponse(status=401), GetMyMeterAuthError),
        (FakeResponse(status=302), GetMyMeterApiError),
        (
            FakeResponse(
                status=500, text="<html>failure</html>", content_type="text/html"
            ),
            GetMyMeterAuthError,
        ),
        (
            FakeResponse(
                text="<html><body>error</body></html>", content_type="text/html"
            ),
            GetMyMeterApiError,
        ),
    ],
)
async def test_http_failures_are_static_and_safe(
    response: FakeResponse, exception: type[Exception]
) -> None:
    """HTTP and malformed responses never expose the token in an exception."""
    token = TEST_CONFIG[CONF_TOKEN]
    with pytest.raises(exception) as raised:
        await GetMyMeterApi(FakeSession(response), TEST_CONFIG).async_fetch_bucket("d")
    assert token not in str(raised.value)
    assert token not in repr(raised.value)


@pytest.mark.asyncio
async def test_timeout_and_connection_error_are_classified() -> None:
    """The explicit request timeout cannot stall setup forever."""
    with pytest.raises(GetMyMeterConnectionError):
        await GetMyMeterApi(
            FakeSession(TimeoutError()), TEST_CONFIG
        ).async_fetch_bucket("d")


@pytest.mark.asyncio
async def test_empty_token_fails_before_request() -> None:
    """An absent token cannot produce a portal request."""
    session = FakeSession(FakeResponse())
    with pytest.raises(GetMyMeterAuthError):
        await GetMyMeterApi(
            session, {**TEST_CONFIG, CONF_TOKEN: ""}
        ).async_fetch_bucket("d")
    assert not session.calls
