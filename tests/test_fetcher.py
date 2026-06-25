"""Tests for asynchronous source fetching."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from commodity_etf_dashboard.etl.fetcher import FetchSettings, ProviderRateLimiter, fetch_source


class FakeResponse:
    """Small httpx.Response stand-in for fetcher tests."""

    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)


class FakeClient:
    """Async client with queued outcomes."""

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def get(self, url: str, timeout: float) -> object:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def source() -> dict[str, object]:
    """Return a minimal Alpha Vantage source config."""
    return {
        "name": "SPDR Gold Shares",
        "type": "etf",
        "symbol": "GLD",
        "api_provider": "alpha_vantage",
        "endpoint_url": "https://example.test/query",
        "response_path": "Time Series (Daily)",
    }


def test_fetch_source_returns_expected_schema() -> None:
    """A successful HTTP response is wrapped in the raw response envelope."""
    client = FakeClient([FakeResponse(200, {"ok": True})])
    result = asyncio.run(
        fetch_source(
            client,
            source(),
            FetchSettings(retry_attempts=1, retry_base_delay_seconds=0),
            ProviderRateLimiter({"alpha_vantage": 0}),
        )
    )

    assert result["symbol"] == "GLD"
    assert result["provider"] == "alpha_vantage"
    assert result["status_code"] == 200
    assert result["data"] == {"ok": True}
    assert "latency_ms" in result


def test_fetch_source_retries_429_and_500_status_codes() -> None:
    """Retryable status codes are retried before returning success."""
    client = FakeClient([FakeResponse(429, {}), FakeResponse(500, {}), FakeResponse(200, {"ok": True})])
    result = asyncio.run(
        fetch_source(
            client,
            source(),
            FetchSettings(retry_attempts=3, retry_base_delay_seconds=0),
            ProviderRateLimiter({"alpha_vantage": 0}),
        )
    )

    assert client.calls == 3
    assert result["status_code"] == 200
    assert result["data"] == {"ok": True}


def test_fetch_source_timeout_raises_after_retries() -> None:
    """Timeouts are retried and then re-raised after the configured attempts."""
    client = FakeClient([httpx.TimeoutException("timeout"), httpx.TimeoutException("timeout")])

    with pytest.raises(httpx.TimeoutException):
        asyncio.run(
            fetch_source(
                client,
                source(),
                FetchSettings(retry_attempts=2, retry_base_delay_seconds=0),
                ProviderRateLimiter({"alpha_vantage": 0}),
            )
        )

    assert client.calls == 2
