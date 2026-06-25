"""MySQL bulk upsert loader with connection pooling and testable DB adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from loguru import logger

try:
    from mysql.connector import pooling
except ImportError:  # pragma: no cover - exercised only when optional dependency is absent.
    pooling = None


@dataclass
class LoadResult:
    """Summary of a price-history load."""

    inserted: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


class MarketDataLoader:
    """Load normalized market records into a relational database."""

    def __init__(
        self,
        db_config: dict[str, Any] | None = None,
        *,
        connection_factory: Callable[[], Any] | None = None,
        dialect: str = "mysql",
        batch_size: int = 1000,
    ) -> None:
        self.dialect = dialect
        self.batch_size = batch_size
        self._connection_factory = connection_factory
        self._pool: Any | None = None
        if connection_factory is None and db_config is not None:
            if pooling is None:
                raise RuntimeError("mysql-connector-python is required for MySQL loading")
            self._pool = pooling.MySQLConnectionPool(
                pool_name="market_intelligence_pool",
                pool_size=int(db_config.get("pool_size", 5)),
                host=db_config["host"],
                port=int(db_config.get("port", 3306)),
                database=db_config["name"],
                user=db_config["user"],
                password=db_config["password"],
            )

    def load_all(self, records: pd.DataFrame) -> LoadResult:
        """Upsert normalized OHLCV records in chunks."""
        if records.empty:
            return LoadResult()
        result = LoadResult()
        connection = self._get_connection()
        try:
            for batch in _chunks(records.to_dict(orient="records"), self.batch_size):
                batch_result = self._upsert_batch(connection, batch)
                result.inserted += batch_result.inserted
                result.updated += batch_result.updated
            connection.commit()
        except Exception as exc:  # mysql/sqlite drivers raise different concrete classes.
            connection.rollback()
            result.errors.append(str(exc))
            logger.bind(error=str(exc)).error("load_failed")
        finally:
            connection.close()
        return result

    def write_etl_run(
        self,
        *,
        duration_sec: float,
        rows_inserted: int,
        rows_updated: int,
        errors: list[str],
        status: str,
    ) -> None:
        """Persist an ETL run audit record."""
        connection = self._get_connection()
        sql = (
            "INSERT INTO etl_runs (duration_sec, rows_inserted, rows_updated, errors, status) "
            "VALUES (%s, %s, %s, %s, %s)"
            if self.dialect == "mysql"
            else "INSERT INTO etl_runs (duration_sec, rows_inserted, rows_updated, errors, status) VALUES (?, ?, ?, ?, ?)"
        )
        try:
            cursor = connection.cursor()
            cursor.execute(sql, (duration_sec, rows_inserted, rows_updated, "\n".join(errors), status))
            connection.commit()
        finally:
            connection.close()

    def _get_connection(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()
        if self._pool is None:
            raise ValueError("A db_config or connection_factory is required")
        return self._pool.get_connection()

    def _upsert_batch(self, connection: Any, rows: list[dict[str, Any]]) -> LoadResult:
        if not rows:
            return LoadResult()
        symbol_ids = self._ensure_symbols(connection, rows)
        payload = [
            (
                symbol_ids[row["symbol"]],
                _format_ts(row["ts"]),
                _nullable(row.get("open")),
                _nullable(row.get("high")),
                _nullable(row.get("low")),
                _nullable(row.get("close")),
                _nullable(row.get("volume")),
                row.get("source"),
                int(row.get("is_anomaly", 0) or 0),
            )
            for row in rows
        ]
        cursor = connection.cursor()
        before_changes = _total_changes(connection)
        if self.dialect == "mysql":
            sql = (
                "INSERT INTO price_history (symbol_id, ts, open, high, low, close, volume, source, is_anomaly) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE open = VALUES(open), high = VALUES(high), low = VALUES(low), "
                "close = VALUES(close), volume = VALUES(volume), source = VALUES(source), is_anomaly = VALUES(is_anomaly)"
            )
        else:
            sql = (
                "INSERT INTO price_history (symbol_id, ts, open, high, low, close, volume, source, is_anomaly) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol_id, ts) DO UPDATE SET open = excluded.open, high = excluded.high, "
                "low = excluded.low, close = excluded.close, volume = excluded.volume, source = excluded.source, "
                "is_anomaly = excluded.is_anomaly"
            )
        cursor.executemany(sql, payload)
        self._insert_anomaly_events(connection, rows, symbol_ids)
        changed = max(_total_changes(connection) - before_changes, 0)
        updated = max(changed - len(payload), 0)
        inserted = len(payload) - updated
        logger.bind(rows=len(payload), inserted=inserted, updated=updated).info("load_batch_completed")
        return LoadResult(inserted=inserted, updated=updated)

    def _ensure_symbols(self, connection: Any, rows: list[dict[str, Any]]) -> dict[str, int]:
        symbols = sorted({str(row["symbol"]) for row in rows})
        cursor = connection.cursor()
        if self.dialect == "mysql":
            cursor.executemany(
                "INSERT INTO symbols (symbol, name, type, api_source) VALUES (%s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE symbol = VALUES(symbol)",
                [(symbol, symbol, "etf", "etl") for symbol in symbols],
            )
            placeholders = ", ".join(["%s"] * len(symbols))
            cursor.execute("SELECT symbol, id FROM symbols WHERE symbol IN (" + placeholders + ")", tuple(symbols))
        else:
            cursor.executemany(
                "INSERT OR IGNORE INTO symbols (symbol, name, type, api_source) VALUES (?, ?, ?, ?)",
                [(symbol, symbol, "etf", "etl") for symbol in symbols],
            )
            placeholders = ", ".join(["?"] * len(symbols))
            cursor.execute("SELECT symbol, id FROM symbols WHERE symbol IN (" + placeholders + ")", tuple(symbols))
        return {symbol: int(symbol_id) for symbol, symbol_id in cursor.fetchall()}

    def _insert_anomaly_events(self, connection: Any, rows: list[dict[str, Any]], symbol_ids: dict[str, int]) -> None:
        flagged = [
            (
                symbol_ids[row["symbol"]],
                _format_ts(row["ts"]),
                _nullable(row.get("close")),
                _nullable(row.get("z_score")),
                row.get("method") or "zscore_iqr",
            )
            for row in rows
            if int(row.get("is_anomaly", 0) or 0) == 1
        ]
        if not flagged:
            return
        cursor = connection.cursor()
        if self.dialect == "mysql":
            sql = (
                "INSERT INTO anomaly_events (symbol_id, ts, price, z_score, method) "
                "VALUES (%s, %s, %s, %s, %s)"
            )
        else:
            sql = "INSERT INTO anomaly_events (symbol_id, ts, price, z_score, method) VALUES (?, ?, ?, ?, ?)"
        cursor.executemany(sql, flagged)


def load_all(records: pd.DataFrame, db_config: dict[str, Any], batch_size: int = 1000) -> LoadResult:
    """Convenience function for production MySQL loads."""
    return MarketDataLoader(db_config=db_config, batch_size=batch_size).load_all(records)


def _chunks(records: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(records), size):
        yield records[index : index + size]


def _format_ts(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _nullable(value: Any) -> Any:
    return None if pd.isna(value) else value


def _total_changes(connection: Any) -> int:
    return int(getattr(connection, "total_changes", 0))
