"""Pandas-based normalization and validation for raw market API responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd


CANONICAL_COLUMNS = ["symbol", "ts", "open", "high", "low", "close", "volume", "source"]


@dataclass
class TransformResult:
    """Container for valid normalized rows and quarantined invalid rows."""

    records: pd.DataFrame
    quarantine: pd.DataFrame


def transform_all(raw_responses: list[dict[str, Any]]) -> TransformResult:
    """Normalize all raw responses into the unified OHLCV schema."""
    frames: list[pd.DataFrame] = []
    quarantined: list[pd.DataFrame] = []

    for raw in raw_responses:
        if raw.get("error"):
            quarantined.append(
                pd.DataFrame(
                    [
                        {
                            "symbol": raw.get("symbol"),
                            "source": raw.get("provider"),
                            "reason": raw.get("error"),
                        }
                    ]
                )
            )
            continue
        frame = normalize_response(raw)
        valid, quarantine = validate_frame(frame)
        if not valid.empty:
            frames.append(valid)
        if not quarantine.empty:
            quarantined.append(quarantine)

    records = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CANONICAL_COLUMNS)
    quarantine_df = pd.concat(quarantined, ignore_index=True) if quarantined else pd.DataFrame()
    return TransformResult(records=records, quarantine=quarantine_df)


def normalize_response(raw: dict[str, Any]) -> pd.DataFrame:
    """Normalize one raw API response into canonical columns."""
    provider = str(raw.get("provider", ""))
    data = raw.get("data") or {}
    symbol = str(raw.get("symbol"))

    if provider == "alpha_vantage":
        frame = _normalize_alpha_vantage(data, symbol, provider)
    elif provider == "yahoo_finance":
        frame = _normalize_records(data.get("records", []), symbol, provider)
    elif provider == "twelve_data":
        frame = _normalize_records(data.get("values", []), symbol, provider)
    elif provider == "eia":
        frame = _normalize_eia(_path_get(data, raw.get("response_path")), symbol, provider)
    elif provider == "usda_nass":
        frame = _normalize_usda(_path_get(data, raw.get("response_path")), symbol, provider)
    elif provider in {"metals_api", "open_exchange_rates"}:
        frame = _normalize_spot_value(data, raw, symbol, provider)
    else:
        path_value = _path_get(data, raw.get("response_path"))
        frame = _normalize_records(path_value if isinstance(path_value, list) else [], symbol, provider)

    return _coerce_canonical(frame)


def validate_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate close, timestamp, and duplicate constraints without raising."""
    if frame.empty:
        return frame.reindex(columns=CANONICAL_COLUMNS), pd.DataFrame()

    working = frame.copy()
    now = pd.Timestamp.now(tz="UTC")
    working["reason"] = ""
    working.loc[working["close"].isna() | (working["close"] <= 0), "reason"] += "close must be positive;"
    working.loc[working["ts"].isna(), "reason"] += "timestamp is required;"
    working.loc[working["ts"] > now, "reason"] += "timestamp cannot be in future;"
    duplicate_mask = working.duplicated(subset=["symbol", "ts"], keep="first")
    working.loc[duplicate_mask, "reason"] += "duplicate symbol timestamp;"

    quarantine = working[working["reason"] != ""].copy()
    valid = working[working["reason"] == ""].copy()
    valid = valid[CANONICAL_COLUMNS].sort_values(["symbol", "ts"]).reset_index(drop=True)
    return valid, quarantine.reset_index(drop=True)


def _normalize_alpha_vantage(data: dict[str, Any], symbol: str, provider: str) -> pd.DataFrame:
    series = data.get("Time Series (Daily)") or data.get("Time Series (5min)") or {}
    if not isinstance(series, dict):
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    frame = pd.DataFrame.from_dict(series, orient="index").reset_index(names="ts")
    frame = frame.rename(
        columns={
            "1. open": "open",
            "2. high": "high",
            "3. low": "low",
            "4. close": "close",
            "5. volume": "volume",
        }
    )
    frame["symbol"] = symbol
    frame["source"] = provider
    return frame


def _normalize_records(records: list[dict[str, Any]], symbol: str, provider: str) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    frame = pd.DataFrame.from_records(records)
    rename_map = {
        "date": "ts",
        "datetime": "ts",
        "timestamp": "ts",
        "Date": "ts",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "close",
        "Volume": "volume",
    }
    frame = frame.rename(columns=rename_map)
    frame["symbol"] = symbol
    frame["source"] = provider
    return frame


def _normalize_eia(records: Any, symbol: str, provider: str) -> pd.DataFrame:
    if not isinstance(records, list) or not records:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    frame = pd.DataFrame.from_records(records)
    frame = frame.rename(columns={"period": "ts", "value": "close"})
    frame["open"] = frame.get("open", frame["close"])
    frame["high"] = frame.get("high", frame["close"])
    frame["low"] = frame.get("low", frame["close"])
    frame["volume"] = pd.NA
    frame["symbol"] = symbol
    frame["source"] = provider
    return frame


def _normalize_usda(records: Any, symbol: str, provider: str) -> pd.DataFrame:
    if not isinstance(records, list) or not records:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    frame = pd.DataFrame.from_records(records)
    value_col = "Value" if "Value" in frame.columns else "value"
    date_col = "week_ending" if "week_ending" in frame.columns else "year"
    frame = frame.rename(columns={date_col: "ts", value_col: "close"})
    frame["close"] = frame["close"].astype(str).str.replace(",", "", regex=False)
    frame["open"] = frame["close"]
    frame["high"] = frame["close"]
    frame["low"] = frame["close"]
    frame["volume"] = pd.NA
    frame["symbol"] = symbol
    frame["source"] = provider
    return frame


def _normalize_spot_value(data: dict[str, Any], raw: dict[str, Any], symbol: str, provider: str) -> pd.DataFrame:
    value = _path_get(data, raw.get("response_path"))
    ts_value = data.get("timestamp") or data.get("date") or raw.get("fetched_at") or datetime.now(timezone.utc).isoformat()
    if isinstance(value, dict):
        value = next(iter(value.values()), None)
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "ts": ts_value,
                "open": value,
                "high": value,
                "low": value,
                "close": value,
                "volume": pd.NA,
                "source": provider,
            }
        ]
    )


def _coerce_canonical(frame: pd.DataFrame) -> pd.DataFrame:
    for column in CANONICAL_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    canonical = frame[CANONICAL_COLUMNS].copy()
    canonical["ts"] = pd.to_datetime(canonical["ts"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close"]:
        canonical[column] = pd.to_numeric(canonical[column], errors="coerce")
    canonical["volume"] = pd.to_numeric(canonical["volume"], errors="coerce").astype("Int64")
    return canonical


def _path_get(data: Any, path: Any) -> Any:
    if not path:
        return data
    current = data
    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
