"""ETL orchestration for fetch, transform, load, and analytics execution."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from loguru import logger
from dotenv import load_dotenv

from commodity_etf_dashboard.analytics.anomaly_detection import detect_anomalies
from commodity_etf_dashboard.etl.fetcher import FetchSettings, expand_env_vars, fetch_all
from commodity_etf_dashboard.etl.loader import MarketDataLoader
from commodity_etf_dashboard.etl.transformer import transform_all


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(config_path: Path | None = None, sources_path: Path | None = None) -> dict[str, Any]:
    """Run the complete ETL cycle once."""
    run_id = str(uuid4())
    started = time.perf_counter()
    load_dotenv(PROJECT_ROOT / ".env")
    config = _load_yaml(config_path or PROJECT_ROOT / "config" / "config.yaml")
    sources_config = _load_yaml(sources_path or PROJECT_ROOT / "config" / "api_sources.yaml")
    sources = sources_config["sources"]
    errors: list[str] = []

    _log(run_id, "fetch", "all", "started", 0, 0)
    fetch_settings = FetchSettings(
        timeout_seconds=float(config["etl"]["request_timeout_seconds"]),
        retry_attempts=int(config["etl"]["retry_attempts"]),
        retry_base_delay_seconds=float(config["etl"]["retry_base_delay_seconds"]),
    )
    raw = asyncio.run(fetch_all(sources, fetch_settings))
    fetch_errors = [str(item["error"]) for item in raw if item.get("error")]
    errors.extend(fetch_errors)
    _log(run_id, "fetch", "all", "completed", len(raw), started)

    transform_started = time.perf_counter()
    transformed = transform_all(raw)
    errors.extend(transformed.quarantine.get("reason", []).dropna().astype(str).tolist() if not transformed.quarantine.empty else [])
    _log(run_id, "transform", "all", "completed", len(transformed.records), transform_started)

    analytics_started = time.perf_counter()
    if not transformed.records.empty:
        transformed.records = detect_anomalies(transformed.records).drop(
            columns=[column for column in ["rolling_mean", "rolling_std", "iqr_flag"] if column in transformed.records.columns]
        )
    _log(run_id, "analytics", "all", "completed", len(transformed.records), analytics_started)

    load_started = time.perf_counter()
    loader = MarketDataLoader(
        db_config=_expand_config(config["database"]),
        batch_size=int(config["etl"]["batch_size"]),
    )
    load_result = loader.load_all(transformed.records)
    errors.extend(load_result.errors)
    _log(run_id, "load", "all", "completed", len(transformed.records), load_started)

    duration_sec = time.perf_counter() - started
    status = "success" if not errors else ("partial" if load_result.inserted or load_result.updated else "failed")
    loader.write_etl_run(
        duration_sec=duration_sec,
        rows_inserted=load_result.inserted,
        rows_updated=load_result.updated,
        errors=errors,
        status=status,
    )
    return {
        "run_id": run_id,
        "status": status,
        "duration_sec": duration_sec,
        "rows_inserted": load_result.inserted,
        "rows_updated": load_result.updated,
        "errors": errors,
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _expand_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: expand_env_vars(str(value)) if isinstance(value, str) else value for key, value in config.items()}


def _log(run_id: str, stage: str, symbol: str, status: str, rows: int, started: float) -> None:
    duration_ms = int((time.perf_counter() - started) * 1000) if started else 0
    logger.info(json.dumps({"run_id": run_id, "stage": stage, "symbol": symbol, "status": status, "rows": rows, "duration_ms": duration_ms}))
