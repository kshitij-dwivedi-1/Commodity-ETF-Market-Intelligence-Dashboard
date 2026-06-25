"""Asynchronous API fetching with retry, rate limiting, and structured logs."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd
from loguru import logger

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - exercised only when optional dependency is absent.
    yf = None


RATE_LIMIT_SECONDS: dict[str, float] = {
    "alpha_vantage": 12.0,
    "twelve_data": 8.0,
    "metals_api": 1.0,
    "eia": 0.5,
    "usda_nass": 0.5,
    "open_exchange_rates": 1.0,
    "yahoo_finance": 0.2,
}


@dataclass(frozen=True)
class FetchSettings:
    """Runtime controls for API fetches."""

    timeout_seconds: float = 10.0
    retry_attempts: int = 3
    retry_base_delay_seconds: float = 2.0


class ProviderRateLimiter:
    """Cooperative per-provider async rate limiter."""

    def __init__(self, limits: dict[str, float] | None = None) -> None:
        self._limits = limits or RATE_LIMIT_SECONDS
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_called: dict[str, float] = {}

    async def wait(self, provider: str) -> None:
        """Wait long enough to respect the provider interval."""
        interval = self._limits.get(provider, 0.0)
        lock = self._locks.setdefault(provider, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            elapsed = now - self._last_called.get(provider, 0.0)
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
            self._last_called[provider] = time.monotonic()


def expand_env_vars(value: str) -> str:
    """Expand ${VAR} and ${VAR:-default} expressions in config strings."""
    result = value
    while "${" in result:
        start = result.index("${")
        end = result.index("}", start)
        expression = result[start + 2 : end]
        if ":-" in expression:
            name, default = expression.split(":-", 1)
            replacement = os.getenv(name, default)
        else:
            replacement = os.getenv(expression, "")
        result = f"{result[:start]}{replacement}{result[end + 1:]}"
    return result


async def fetch_source(
    client: httpx.AsyncClient,
    source: dict[str, Any],
    settings: FetchSettings | None = None,
    rate_limiter: ProviderRateLimiter | None = None,
) -> dict[str, Any]:
    """Fetch one configured source and return a normalized raw payload envelope."""
    effective_settings = settings or FetchSettings()
    limiter = rate_limiter or ProviderRateLimiter()
    provider = str(source["api_provider"])
    symbol = str(source["symbol"])
    started = time.perf_counter()

    if provider == "yahoo_finance":
        data = await _fetch_yfinance(symbol)
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.bind(symbol=symbol, provider=provider, status_code=200, latency_ms=latency_ms).info(
            "fetch_completed"
        )
        return _envelope(source, 200, latency_ms, data)

    url = expand_env_vars(str(source.get("endpoint_url", "")))
    last_error: str | None = None

    for attempt in range(1, effective_settings.retry_attempts + 1):
        await limiter.wait(provider)
        try:
            response = await client.get(url, timeout=effective_settings.timeout_seconds)
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.bind(
                symbol=symbol,
                provider=provider,
                status_code=response.status_code,
                latency_ms=latency_ms,
                attempt=attempt,
            ).info("fetch_attempt")
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = f"retryable status {response.status_code}"
                if attempt < effective_settings.retry_attempts:
                    await asyncio.sleep(effective_settings.retry_base_delay_seconds * (2 ** (attempt - 1)))
                    continue
            response.raise_for_status()
            return _envelope(source, response.status_code, latency_ms, response.json())
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError, ValueError) as exc:
            last_error = str(exc)
            if attempt < effective_settings.retry_attempts:
                await asyncio.sleep(effective_settings.retry_base_delay_seconds * (2 ** (attempt - 1)))
                continue
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.bind(symbol=symbol, provider=provider, latency_ms=latency_ms, error=last_error).error(
                "fetch_failed"
            )
            if isinstance(exc, httpx.TimeoutException):
                raise
            return _envelope(source, None, latency_ms, None, error=last_error)

    latency_ms = int((time.perf_counter() - started) * 1000)
    return _envelope(source, None, latency_ms, None, error=last_error or "unknown fetch failure")


async def fetch_all(sources: list[dict[str, Any]], settings: FetchSettings | None = None) -> list[dict[str, Any]]:
    """Fetch all configured sources concurrently."""
    effective_settings = settings or FetchSettings()
    limiter = ProviderRateLimiter()
    timeout = httpx.Timeout(effective_settings.timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [fetch_source(client, source, effective_settings, limiter) for source in sources]
        return await asyncio.gather(*tasks)


async def _fetch_yfinance(symbol: str) -> dict[str, Any]:
    """Fetch daily OHLCV data from yfinance without blocking the event loop."""

    def download() -> dict[str, Any]:
        if yf is None:
            raise RuntimeError("yfinance is required for yahoo_finance sources")
        ticker = "KC=F" if symbol == "COFFEE" else symbol
        frame = yf.download(ticker, period="90d", interval="1d", progress=False, auto_adjust=False)
        if frame.empty:
            return {"records": []}
        frame = frame.reset_index()
        frame.columns = [str(col[0] if isinstance(col, tuple) else col).lower().replace(" ", "_") for col in frame.columns]
        return {"records": frame.to_dict(orient="records")}

    return await asyncio.to_thread(download)


def _envelope(
    source: dict[str, Any],
    status_code: int | None,
    latency_ms: int,
    data: Any,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "symbol": source.get("symbol"),
        "name": source.get("name"),
        "type": source.get("type"),
        "provider": source.get("api_provider"),
        "response_path": source.get("response_path"),
        "status_code": status_code,
        "latency_ms": latency_ms,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "error": error,
    }
