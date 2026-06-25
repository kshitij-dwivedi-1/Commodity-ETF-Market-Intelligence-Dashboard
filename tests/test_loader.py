"""Tests for relational load and upsert behavior."""

from __future__ import annotations

import sqlite3
from typing import Any

import pandas as pd

from commodity_etf_dashboard.etl.loader import LoadResult, MarketDataLoader


class NonClosingConnection:
    """SQLite wrapper that lets loader.close() run without closing test DB."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    @property
    def total_changes(self) -> int:
        return self.connection.total_changes

    def cursor(self) -> sqlite3.Cursor:
        return self.connection.cursor()

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        return None


def create_sqlite_db() -> sqlite3.Connection:
    """Create an in-memory schema-compatible subset."""
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE symbols (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL UNIQUE, name TEXT NOT NULL, type TEXT NOT NULL, api_source TEXT)"
    )
    connection.execute(
        "CREATE TABLE price_history (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol_id INTEGER NOT NULL, ts TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL NOT NULL, volume INTEGER, source TEXT, is_anomaly INTEGER DEFAULT 0, UNIQUE(symbol_id, ts))"
    )
    connection.execute(
        "CREATE TABLE anomaly_events (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol_id INTEGER NOT NULL, ts TEXT NOT NULL, price REAL, z_score REAL, method TEXT)"
    )
    connection.commit()
    return connection


def records(count: int, symbol: str = "SPY") -> pd.DataFrame:
    """Generate deterministic normalized records."""
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "ts": pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=index),
                "open": 100 + index,
                "high": 101 + index,
                "low": 99 + index,
                "close": 100.5 + index,
                "volume": 1000 + index,
                "source": "test",
            }
            for index in range(count)
        ]
    )


def test_batch_upsert_inserts_new_rows_correctly() -> None:
    """New rows are inserted into price_history."""
    connection = create_sqlite_db()
    loader = MarketDataLoader(connection_factory=lambda: NonClosingConnection(connection), dialect="sqlite", batch_size=1000)

    result = loader.load_all(records(2))

    count = connection.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert result.errors == []
    assert count == 2


def test_upsert_updates_existing_rows_on_duplicate_key() -> None:
    """Existing symbol/timestamp rows are updated on duplicate keys."""
    connection = create_sqlite_db()
    loader = MarketDataLoader(connection_factory=lambda: NonClosingConnection(connection), dialect="sqlite", batch_size=1000)
    first = records(1)
    second = first.copy()
    second.loc[0, "close"] = 123.45

    loader.load_all(first)
    loader.load_all(second)

    close = connection.execute("SELECT close FROM price_history").fetchone()[0]
    count = connection.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert count == 1
    assert close == 123.45


def test_chunk_behavior_for_2500_rows() -> None:
    """A 2,500 row load is split into 1,000, 1,000, and 500 row batches."""
    connection = create_sqlite_db()
    loader = MarketDataLoader(connection_factory=lambda: NonClosingConnection(connection), dialect="sqlite", batch_size=1000)
    batch_sizes: list[int] = []

    def fake_upsert(conn: Any, batch: list[dict[str, Any]]) -> LoadResult:
        batch_sizes.append(len(batch))
        return LoadResult(inserted=len(batch))

    loader._upsert_batch = fake_upsert  # type: ignore[method-assign]
    result = loader.load_all(records(2500))

    assert batch_sizes == [1000, 1000, 500]
    assert result.inserted == 2500
