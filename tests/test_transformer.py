"""Tests for response normalization and validation."""

from __future__ import annotations

import pandas as pd

from commodity_etf_dashboard.etl.transformer import normalize_response, transform_all, validate_frame


def test_normalizes_alpha_vantage_format() -> None:
    """Alpha Vantage daily series maps to canonical OHLCV columns."""
    raw = {
        "symbol": "GLD",
        "provider": "alpha_vantage",
        "data": {
            "Time Series (Daily)": {
                "2024-01-02": {
                    "1. open": "190.00",
                    "2. high": "192.00",
                    "3. low": "189.50",
                    "4. close": "191.25",
                    "5. volume": "1000",
                }
            }
        },
    }

    frame = normalize_response(raw)

    assert frame.loc[0, "symbol"] == "GLD"
    assert frame.loc[0, "close"] == 191.25
    assert str(frame.loc[0, "ts"].tz) == "UTC"


def test_normalizes_yfinance_records() -> None:
    """yfinance records map title-case columns to canonical columns."""
    raw = {
        "symbol": "SPY",
        "provider": "yahoo_finance",
        "data": {
            "records": [
                {
                    "Date": "2024-01-02 09:30:00-05:00",
                    "Open": 470,
                    "High": 475,
                    "Low": 468,
                    "Close": 474,
                    "Volume": 12345,
                }
            ]
        },
    }

    frame = normalize_response(raw)

    assert frame.loc[0, "symbol"] == "SPY"
    assert frame.loc[0, "close"] == 474
    assert frame.loc[0, "ts"].hour == 14


def test_quarantines_non_positive_close() -> None:
    """Rows with close <= 0 are quarantined instead of raising."""
    raw = {
        "symbol": "SLV",
        "provider": "yahoo_finance",
        "data": {"records": [{"Date": "2024-01-02", "Open": 1, "High": 1, "Low": 1, "Close": 0, "Volume": 10}]},
    }

    result = transform_all([raw])

    assert result.records.empty
    assert "close must be positive" in result.quarantine.loc[0, "reason"]


def test_utc_conversion_of_various_timezone_inputs() -> None:
    """Mixed timezone strings become UTC timestamps."""
    frame = pd.DataFrame(
        [
            {"symbol": "A", "ts": "2024-01-02T10:00:00-05:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "source": "x"},
            {"symbol": "A", "ts": "2024-01-02T15:00:00Z", "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "source": "x"},
        ]
    )
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)

    valid, quarantine = validate_frame(frame)

    assert quarantine.loc[0, "reason"] == "duplicate symbol timestamp;"
    assert valid.loc[0, "ts"].tzinfo is not None


def test_duplicate_timestamp_detection() -> None:
    """Only the first row for a duplicate symbol timestamp remains valid."""
    frame = pd.DataFrame(
        [
            {"symbol": "QQQ", "ts": "2024-01-02", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "source": "x"},
            {"symbol": "QQQ", "ts": "2024-01-02", "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "source": "x"},
        ]
    )
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)

    valid, quarantine = validate_frame(frame)

    assert len(valid) == 1
    assert len(quarantine) == 1
    assert "duplicate symbol timestamp" in quarantine.loc[0, "reason"]
