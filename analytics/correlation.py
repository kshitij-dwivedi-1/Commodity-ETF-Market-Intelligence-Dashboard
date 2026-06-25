"""Rolling Pearson correlation matrix computation and persistence."""

from __future__ import annotations

from typing import Any

import pandas as pd


def compute_correlation_matrix(
    symbol_ids: list[int],
    window_days: int = 30,
    connection: Any | None = None,
) -> pd.DataFrame:
    """Pull recent close prices, compute pairwise correlations, and upsert results."""
    if connection is None:
        raise ValueError("connection is required")
    placeholders = ", ".join(["%s"] * len(symbol_ids))
    sql = (
        "SELECT symbol_id, ts, close FROM price_history "
        "WHERE symbol_id IN (" + placeholders + ") AND ts >= UTC_TIMESTAMP() - INTERVAL %s DAY"
    )
    frame = pd.read_sql(sql, connection, params=tuple(symbol_ids + [window_days]))
    if frame.empty:
        return pd.DataFrame()

    wide = frame.pivot_table(index="ts", columns="symbol_id", values="close", aggfunc="last").sort_index()
    corr = wide.corr(method="pearson")
    rows = [
        (int(symbol_a), int(symbol_b), window_days, None if pd.isna(value) else float(value))
        for symbol_a in corr.index
        for symbol_b, value in corr.loc[symbol_a].items()
    ]
    cursor = connection.cursor()
    cursor.executemany(
        "INSERT INTO correlation_matrix (symbol_a_id, symbol_b_id, window_days, correlation) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE correlation = VALUES(correlation), computed_at = CURRENT_TIMESTAMP",
        rows,
    )
    connection.commit()
    return corr
